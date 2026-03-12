from typing import Any, Dict, List

from content_core import extract_content
from content_core.common import ProcessSourceState
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.ai.models import Model, ModelManager
from open_notebook.database.repository import admin_repo_query
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation


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


async def content_process(state: SourceState) -> dict:
    settings = await _get_content_settings()
    content_state: Dict[str, Any] = state["content_state"]  # type: ignore[assignment]

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
        # Continue without custom audio model (content-core will use its default)

    processed_state = await extract_content(content_state)

    if not processed_state.content or not processed_state.content.strip():
        url = processed_state.url or ""
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

