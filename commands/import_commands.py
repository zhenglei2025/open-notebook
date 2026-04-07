import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.database.repository import ensure_record_id, set_current_user_db
from open_notebook.domain.import_job import ImportJob, ImportJobItem
from open_notebook.domain.notebook import Source
from open_notebook.domain.transformation import Transformation

try:
    from open_notebook.graphs.source import source_graph
except ImportError as e:
    logger.error(f"Failed to import source graph for import jobs: {e}")
    raise ValueError("source graph not available")

MAX_ARCHIVE_DEPTH = 8
MAX_ARCHIVE_FILES = 1000
_SKIP_ARCHIVE_FILENAMES = {".ds_store", "thumbs.db"}


@dataclass
class ExtractedArchiveFile:
    file_path: str
    display_title: str


class ImportJobProcessingInput(CommandInput):
    import_job_id: str
    user_db_name: Optional[str] = None


class ImportJobProcessingOutput(CommandOutput):
    success: bool
    import_job_id: str
    processed_items: int = 0
    failed_items: int = 0
    processing_time: float
    error_message: Optional[str] = None


def _delete_path_safely(path: str | Path | None) -> None:
    if not path:
        return

    try:
        target = Path(path)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
    except Exception as e:
        logger.warning(f"Failed to clean up path {path}: {e}")


def _is_zip_path(path: str | None) -> bool:
    return bool(path and Path(path).suffix.lower() == ".zip")


def _is_supported_archive_member(path: Path) -> bool:
    if not path.parts:
        return False

    if any(part in {"", ".", "..", "__MACOSX"} for part in path.parts):
        return False

    leaf = path.name.lower()
    if leaf in _SKIP_ARCHIVE_FILENAMES or leaf.startswith("._"):
        return False

    return not path.name.startswith(".")


def _make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _extract_zip_recursive(
    archive_path: Path,
    destination_root: Path,
    *,
    prefix: Path = Path(),
    depth: int = 0,
    collected_files: list[ExtractedArchiveFile] | None = None,
) -> list[ExtractedArchiveFile]:
    if depth > MAX_ARCHIVE_DEPTH:
        raise ValueError(f"ZIP nesting is too deep (>{MAX_ARCHIVE_DEPTH} levels).")

    if collected_files is None:
        collected_files = []

    destination_root_resolved = destination_root.resolve()

    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue

            member_path = Path(member.filename)
            if not _is_supported_archive_member(member_path):
                continue

            relative_target = prefix / member_path
            target_path = _make_unique_path(destination_root / relative_target)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_target = target_path.resolve()
            if not str(resolved_target).startswith(str(destination_root_resolved)):
                logger.warning(f"Skipping unsafe archive member path: {member.filename}")
                continue

            with archive.open(member, "r") as source_fp, open(target_path, "wb") as dest_fp:
                shutil.copyfileobj(source_fp, dest_fp)

            if _is_zip_path(target_path.name):
                _extract_zip_recursive(
                    target_path,
                    destination_root,
                    prefix=relative_target.parent / target_path.stem,
                    depth=depth + 1,
                    collected_files=collected_files,
                )
                _delete_path_safely(target_path)
                continue

            collected_files.append(
                ExtractedArchiveFile(
                    file_path=str(target_path),
                    display_title=relative_target.as_posix(),
                )
            )

            if len(collected_files) > MAX_ARCHIVE_FILES:
                raise ValueError(
                    f"ZIP contains too many importable files (>{MAX_ARCHIVE_FILES})."
                )

    return collected_files


async def _load_transformations(transformation_ids: List[str]) -> List[Transformation]:
    transformations = []
    for trans_id in transformation_ids:
        transformation = await Transformation.get(trans_id)
        if not transformation:
            raise ValueError(f"Transformation '{trans_id}' not found")
        transformations.append(transformation)
    return transformations


async def _save_job(job: ImportJob) -> None:
    await job.save()


async def _mark_item_failed(
    job: ImportJob,
    item: ImportJobItem,
    error_message: str,
) -> None:
    item.status = "failed"
    item.error_message = error_message
    await item.save()

    job.failed_items += 1
    job.current_item = item.display_name
    await _save_job(job)


async def _process_file_item(
    job: ImportJob,
    item: ImportJobItem,
    transformations: List[Transformation],
) -> None:
    job.status = "running"
    job.current_item = item.display_name
    await _save_job(job)

    item.status = "processing"
    item.error_message = None
    await item.save()

    source: Optional[Source] = None
    try:
        source = Source(title=Path(item.name).stem or item.name, topics=[])
        await source.save()

        for notebook_id in job.notebooks:
            await source.add_to_notebook(notebook_id)

        result = await source_graph.ainvoke(  # type: ignore[arg-type]
            {
                "content_state": {
                    "file_path": item.file_path,
                    "delete_source": job.delete_source,
                    "title": Path(item.name).stem or item.name,
                },
                "notebook_ids": job.notebooks,
                "apply_transformations": transformations,
                "embed": job.embed,
                "source_id": str(source.id),
            }
        )

        processed_source = result["source"]
        item.status = "completed"
        item.source_id = str(processed_source.id)
        item.error_message = None
        await item.save()

        job.completed_items += 1
        job.current_item = item.display_name
        await _save_job(job)
    except Exception as e:
        logger.error(f"Failed to process import item {item.display_name}: {e}")
        if source and source.id:
            try:
                await source.delete()
            except Exception:
                logger.warning(f"Failed to clean up partial source for item {item.id}")
        await _mark_item_failed(job, item, str(e))


async def _expand_archive_item(
    job: ImportJob,
    item: ImportJobItem,
    next_sequence: int,
) -> tuple[list[ImportJobItem], int]:
    job.status = "extracting"
    job.current_item = item.display_name
    await _save_job(job)

    item.status = "extracting"
    item.error_message = None
    await item.save()

    archive_root = Path(item.file_path).parent / f"{Path(item.name).stem}_expanded"
    archive_root.mkdir(parents=True, exist_ok=True)

    try:
        extracted_files = _extract_zip_recursive(Path(item.file_path), archive_root)
        if not extracted_files:
            raise ValueError("No importable files were found inside the ZIP archive.")

        created_items: list[ImportJobItem] = []
        for extracted in extracted_files:
            child = ImportJobItem(
                import_job_id=job.id or "",
                parent_item_id=item.id,
                kind="file",
                status="queued",
                sequence=next_sequence,
                name=Path(extracted.display_title).name,
                display_name=extracted.display_title,
                file_path=extracted.file_path,
            )
            await child.save()
            created_items.append(child)
            next_sequence += 1

        item.status = "completed"
        item.error_message = None
        await item.save()

        job.total_items += len(created_items)
        await _save_job(job)

        _delete_path_safely(item.file_path)
        return created_items, next_sequence
    except Exception as e:
        logger.error(f"Failed to expand archive item {item.display_name}: {e}")
        _delete_path_safely(archive_root)
        await _mark_item_failed(job, item, str(e))
        return [], next_sequence


@command("process_import_job", app="open_notebook", retry=None)
async def process_import_job_command(
    input_data: ImportJobProcessingInput,
) -> ImportJobProcessingOutput:
    start_time = time.time()
    set_current_user_db(input_data.user_db_name)

    try:
        job = await ImportJob.get(input_data.import_job_id)
        job.status = "running"
        if input_data.execution_context:
            job.command_id = str(input_data.execution_context.command_id)
        await _save_job(job)

        transformations = await _load_transformations(job.transformations)
        queue = await job.get_items()
        next_sequence = max([item.sequence for item in queue], default=0) + 1

        while queue:
            item = queue.pop(0)
            if item.status in {"completed", "failed"}:
                continue

            if item.kind == "archive":
                created_items, next_sequence = await _expand_archive_item(
                    job, item, next_sequence
                )
                queue = created_items + queue
                continue

            await _process_file_item(job, item, transformations)

        job.current_item = None
        job.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if job.failed_items == 0:
            job.status = "completed"
            job.error_message = None
        elif job.completed_items == 0:
            job.status = "failed"
            job.error_message = "All import items failed."
        else:
            job.status = "partial_failed"
            job.error_message = (
                f"{job.failed_items} import item(s) failed while "
                f"{job.completed_items} completed."
            )
        await _save_job(job)

        processing_time = time.time() - start_time
        return ImportJobProcessingOutput(
            success=job.status == "completed",
            import_job_id=input_data.import_job_id,
            processed_items=job.completed_items,
            failed_items=job.failed_items,
            processing_time=processing_time,
            error_message=job.error_message,
        )
    except Exception as e:
        logger.error(f"Import job {input_data.import_job_id} failed unexpectedly: {e}")
        try:
            job = await ImportJob.get(input_data.import_job_id)
            job.status = "failed"
            job.current_item = None
            job.error_message = str(e)
            job.completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            await _save_job(job)
        except Exception:
            logger.warning("Failed to persist import job failure state")

        processing_time = time.time() - start_time
        return ImportJobProcessingOutput(
            success=False,
            import_job_id=input_data.import_job_id,
            processed_items=0,
            failed_items=0,
            processing_time=processing_time,
            error_message=str(e),
        )
