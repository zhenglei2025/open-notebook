import asyncio
import os
import shutil
import subprocess
import tempfile
import traceback
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from content_core import extract_content
from content_core.common import ProcessSourceState
from content_core.common.exceptions import UnsupportedTypeException as ContentCoreUnsupportedTypeException
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.ai.models import Model, ModelManager
from open_notebook.database.repository import admin_repo_query
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation

_OFFICE_EXTENSIONS = {".docx", ".docm", ".xlsx", ".pptx"}
_WORD_EXTENSIONS = {".doc", ".docx", ".docm"}
_LEGACY_OFFICE_EXTENSIONS = {".doc", ".wps"}


class SourceState(TypedDict):
    content_state: ProcessSourceState
    apply_transformations: List[Transformation]
    source_id: str
    notebook_ids: List[str]
    source: Source
    embed: bool


async def _get_content_settings() -> dict:
    """Read content settings from admin DB (shared across all users)."""
    try:
        result = await admin_repo_query(
            "SELECT * FROM ONLY open_notebook:content_settings"
        )
        if result:
            row = result[0] if isinstance(result, list) else result
            if isinstance(row, dict):
                return row
    except Exception as e:
        logger.warning(f"Failed to read content settings from admin DB: {e}")
    return {}


def _extract_docx_raw(file_path: str) -> "str | None":
    """
    Brute-force DOCX text extraction by parsing word/document.xml directly.

    Completely bypasses python-docx — opens the DOCX as a ZIP, reads the
    XML entries for document body text, and extracts all <w:t> text nodes.
    Handles corrupted media entries, bad CRC-32, missing files, etc.

    Returns extracted text as markdown-ish string, or None on failure.
    """
    WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Read document.xml — the main text content
            xml_files = [
                "word/document.xml",
                "word/document2.xml",  # Some generators use this
            ]
            doc_xml = None
            for name in xml_files:
                if name in zf.namelist():
                    doc_xml = zf.read(name)
                    break

            if not doc_xml:
                logger.error("[extract_docx_raw] No document.xml found in DOCX")
                return None

            # Parse XML and extract text
            from xml.etree import ElementTree as ET

            root = ET.fromstring(doc_xml)
            paragraphs: list[str] = []

            for para in root.iter(f"{WORD_NS}p"):
                # Check if this is a heading
                heading_level = None
                pPr = para.find(f"{WORD_NS}pPr")
                if pPr is not None:
                    pStyle = pPr.find(f"{WORD_NS}pStyle")
                    if pStyle is not None:
                        style_val = pStyle.get(f"{WORD_NS}val", "")
                        # Match styles like "Heading1", "1", "heading 1", etc.
                        for i in range(1, 7):
                            if str(i) in style_val and (
                                "heading" in style_val.lower()
                                or style_val == str(i)
                            ):
                                heading_level = i
                                break

                # Collect all text runs in this paragraph
                texts: list[str] = []
                for t_elem in para.iter(f"{WORD_NS}t"):
                    if t_elem.text:
                        texts.append(t_elem.text)

                line = "".join(texts).strip()
                if not line:
                    continue

                if heading_level:
                    paragraphs.append(f"\n{'#' * heading_level} {line}\n")
                else:
                    paragraphs.append(line)

            content = "\n\n".join(paragraphs)
            logger.info(
                f"[extract_docx_raw] Extracted {len(paragraphs)} paragraphs, "
                f"{len(content)} chars from {os.path.basename(file_path)}"
            )
            return content if content.strip() else None

    except Exception as e:
        logger.error(f"[extract_docx_raw] Failed: {e}")
        return None


def _word_extraction_error_message(file_path: str) -> str:
    extension = os.path.splitext(file_path)[1].lower()
    if extension == ".doc":
        return (
            "Word 抽取错误：旧版 .doc 文件自动转换失败，"
            "请先转换为 .docx 后重试。"
        )

    if extension == ".wps":
        return (
            "WPS 抽取错误：WPS 文件自动转换失败，"
            "请先转换为 .docx 或 PDF 后重试。"
        )

    return (
        "Word 抽取错误：无法解析此 Word 文件，"
        "请检查文件是否损坏，或转换为 .docx 后重试。"
    )


def _run_conversion_command(
    command: list[str], *, timeout_seconds: int = 120
) -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which(command[0])
    if not executable:
        return None

    full_command = [executable, *command[1:]]
    logger.info(f"[conversion] Running command: {' '.join(full_command)}")
    return subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout_seconds,
        check=False,
    )


def _try_libreoffice_extract_text(file_path: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="legacy-office-") as temp_dir:
        for executable_name in ("soffice", "libreoffice"):
            result = _run_conversion_command(
                [
                    executable_name,
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    temp_dir,
                    file_path,
                ]
            )
            if result is None:
                continue

            if result.returncode != 0:
                logger.warning(
                    f"[conversion] LibreOffice conversion failed for {file_path}: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
                continue

            converted_path = os.path.join(
                temp_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}.txt"
            )
            if not os.path.exists(converted_path):
                logger.warning(
                    f"[conversion] LibreOffice reported success but produced no txt "
                    f"output for {file_path}"
                )
                continue

            content = Path(converted_path).read_text(
                encoding="utf-8", errors="ignore"
            )
            if content.strip():
                logger.info(
                    f"[conversion] LibreOffice extracted {len(content)} chars from "
                    f"{os.path.basename(file_path)}"
                )
                return content

    return None


def _try_antiword_extract_text(file_path: str) -> str | None:
    result = _run_conversion_command(["antiword", file_path], timeout_seconds=60)
    if result is None:
        return None

    if result.returncode != 0:
        logger.warning(
            f"[conversion] antiword failed for {file_path}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
        return None

    content = result.stdout or ""
    if content.strip():
        logger.info(
            f"[conversion] antiword extracted {len(content)} chars from "
            f"{os.path.basename(file_path)}"
        )
        return content

    return None


def _extract_legacy_office_text(file_path: str) -> str | None:
    extension = os.path.splitext(file_path)[1].lower()

    content = _try_libreoffice_extract_text(file_path)
    if content:
        return content

    if extension == ".doc":
        return _try_antiword_extract_text(file_path)

    return None


async def content_process(state: SourceState) -> dict:
    logger.info("[content_process] Starting content processing")
    logger.info(f"[content_process] Source ID: {state.get('source_id')}")

    settings = await _get_content_settings()
    content_state: Dict[str, Any] = state["content_state"]  # type: ignore[assignment]
    explicit_title = content_state.get("title")

    # Log input state details for debugging
    logger.info(f"[content_process] Content state keys: {list(content_state.keys())}")
    file_path = content_state.get("file_path")
    if file_path:
        logger.info(f"[content_process] File path: {file_path}")
        if os.path.exists(file_path):
            logger.info(
                f"[content_process] File exists, size: {os.path.getsize(file_path)} bytes"
            )
        else:
            logger.error(f"[content_process] File does NOT exist: {file_path}")
    if content_state.get("url"):
        logger.info(f"[content_process] URL: {content_state['url']}")

    content_state["url_engine"] = (
        settings.get("default_content_processing_engine_url") or "auto"
    )
    content_state["document_engine"] = (
        settings.get("default_content_processing_engine_doc") or "auto"
    )
    content_state["output_format"] = "markdown"

    # Add speech-to-text model configuration from Default Models
    try:
        model_manager = ModelManager()
        defaults = await model_manager.get_defaults()
        if defaults.default_speech_to_text_model:
            stt_model = await Model.get(defaults.default_speech_to_text_model)
            if stt_model:
                content_state["audio_provider"] = stt_model.provider
                content_state["audio_model"] = stt_model.name
                logger.debug(
                    f"Using speech-to-text model: {stt_model.provider}/{stt_model.name}"
                )
    except Exception as e:
        logger.warning(f"Failed to retrieve speech-to-text model configuration: {e}")

    logger.info("[content_process] Calling extract_content...")
    try:
        processed_state = await extract_content(content_state)
        logger.info("[content_process] extract_content completed successfully")
        logger.info(f"[content_process] Extracted content length: {len(processed_state.content) if processed_state.content else 0}")
    except Exception as e:
        logger.warning(f"[content_process] extract_content failed: {type(e).__name__}: {e}")

        is_word_file = bool(file_path and file_path.lower().endswith(tuple(_WORD_EXTENSIONS)))
        is_legacy_office_file = bool(
            file_path and file_path.lower().endswith(tuple(_LEGACY_OFFICE_EXTENSIONS))
        )
        if is_legacy_office_file and file_path:
            logger.info(
                "[content_process] Attempting legacy office conversion fallback..."
            )
            converted_text = await asyncio.to_thread(
                _extract_legacy_office_text, file_path
            )
            if converted_text and converted_text.strip():
                processed_state = ProcessSourceState(
                    content=converted_text,
                    title=os.path.splitext(os.path.basename(file_path))[0],
                    file_path=file_path,
                    identified_type="text/plain",
                )
            else:
                raise ValueError(_word_extraction_error_message(file_path)) from e

        # Fallback: for .docx files, try raw XML extraction
        elif file_path and file_path.lower().endswith((".docx", ".docm")):
            logger.info("[content_process] Attempting raw DOCX extraction fallback...")
            raw_text = _extract_docx_raw(file_path)
            if raw_text:
                logger.info(
                    f"[content_process] Raw fallback succeeded, {len(raw_text)} chars"
                )
                processed_state = ProcessSourceState(
                    content=raw_text,
                    title=os.path.splitext(os.path.basename(file_path))[0],
                    file_path=file_path,
                    identified_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            else:
                logger.error("[content_process] Raw fallback also failed")
                raise ValueError(_word_extraction_error_message(file_path)) from e
        elif is_word_file and isinstance(
            e, (UnicodeDecodeError, ContentCoreUnsupportedTypeException)
        ):
            raise ValueError(_word_extraction_error_message(file_path)) from e
        else:
            raise

    if not processed_state.content or not processed_state.content.strip():
        url = processed_state.url or ""
        logger.warning(f"[content_process] No content extracted. URL: {url}")
        if url and ("youtube.com" in url or "youtu.be" in url):
            raise ValueError(
                "Could not extract content from this YouTube video. "
                "No transcript or subtitles are available. "
                "Try configuring a Speech-to-Text model in Settings "
                "to transcribe the audio instead."
            )
        raise ValueError(
            "Could not extract any text content from this source. "
            "The content may be empty, inaccessible, or in an unsupported format."
        )

    if explicit_title:
        processed_state.title = explicit_title

    logger.info(f"[content_process] Done, content length: {len(processed_state.content)}")
    return {"content_state": processed_state}


async def save_source(state: SourceState) -> dict:
    content_state = state["content_state"]

    # Get existing source using the provided source_id
    source = await Source.get(state["source_id"])
    if not source:
        raise ValueError(f"Source with ID {state['source_id']} not found")

    # Update the source with processed content
    source.asset = Asset(url=content_state.url, file_path=content_state.file_path)
    source.full_text = content_state.content

    # Preserve existing title if none provided in processed content
    if content_state.title:
        source.title = content_state.title

    await source.save()

    # NOTE: Notebook associations are created by the API immediately for UI responsiveness
    # No need to create them here to avoid duplicate edges

    if state["embed"]:
        if source.full_text and source.full_text.strip():
            logger.debug("Embedding content for vector search")
            await source.vectorize()
        else:
            logger.warning(
                f"Source {source.id} has no text content to embed, skipping vectorization"
            )

    # Submit transformations as background jobs (fire-and-forget)
    # so the main command completes after vectorization and the UI
    # stops showing "processing" while insights generate in background
    if state.get("apply_transformations"):
        from surreal_commands import submit_command
        from open_notebook.database.repository import get_current_user_db

        user_db_name = get_current_user_db()
        for t in state["apply_transformations"]:
            try:
                cmd_id = submit_command(
                    "open_notebook",
                    "run_transformation",
                    {
                        "source_id": str(source.id),
                        "transformation_id": str(t.id),
                        "user_db_name": user_db_name,
                    },
                )
                logger.info(
                    f"Submitted background transformation '{t.name}' "
                    f"for source {source.id}: command_id={cmd_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to submit transformation '{t.name}' "
                    f"for source {source.id}: {e}"
                )

    return {"source": source}


# Create and compile the workflow
# Transformations are now submitted as background jobs in save_source,
# so the graph is: content_process → save_source → END
workflow = StateGraph(SourceState)

# Add nodes
workflow.add_node("content_process", content_process)
workflow.add_node("save_source", save_source)
# Define the graph edges
workflow.add_edge(START, "content_process")
workflow.add_edge("content_process", "save_source")
workflow.add_edge("save_source", END)

# Compile the graph
source_graph = workflow.compile()
