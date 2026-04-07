import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from api.command_service import CommandService
from api.models import ImportJobItemResponse, ImportJobResponse
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.database.repository import get_current_user_db
from open_notebook.domain.import_job import ImportJob, ImportJobItem
from open_notebook.domain.notebook import Notebook
from open_notebook.domain.transformation import Transformation
from open_notebook.exceptions import NotFoundError

router = APIRouter()

UPLOAD_CHUNK_SIZE = 1024 * 1024


def _str_to_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes", "on")


def _parse_json_list(value: Optional[str], field_name: str) -> list[str]:
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON in {field_name} field"
        ) from e

    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=400, detail=f"{field_name} field must be a JSON array"
        )

    return [str(item) for item in parsed]


def _generate_unique_filename(original_filename: str, upload_folder: str) -> str:
    file_path = Path(upload_folder)
    file_path.mkdir(parents=True, exist_ok=True)

    stem = Path(original_filename).stem
    suffix = Path(original_filename).suffix

    counter = 0
    while True:
        filename = (
            original_filename if counter == 0 else f"{stem} ({counter}){suffix}"
        )
        full_path = file_path / filename
        if not full_path.exists():
            return str(full_path)
        counter += 1


async def _save_uploaded_file_stream(
    upload_file: UploadFile,
    upload_folder: str,
) -> str:
    if not upload_file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file is missing a name")

    file_path = _generate_unique_filename(upload_file.filename, upload_folder)
    try:
        with open(file_path, "wb") as dest_fp:
            while True:
                chunk = await upload_file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                dest_fp.write(chunk)
        await upload_file.close()
        return file_path
    except Exception as e:
        logger.error(f"Failed to save uploaded file {upload_file.filename}: {e}")
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=500, detail=f"Failed to save uploaded file: {upload_file.filename}"
        ) from e


async def _serialize_import_job(job: ImportJob) -> ImportJobResponse:
    items = await job.get_items()
    return ImportJobResponse(
        id=job.id or "",
        job_type=job.job_type,
        status=job.status,
        notebooks=job.notebooks,
        transformations=job.transformations,
        embed=job.embed,
        delete_source=job.delete_source,
        total_items=job.total_items,
        completed_items=job.completed_items,
        failed_items=job.failed_items,
        current_item=job.current_item,
        error_message=job.error_message,
        command_id=job.command_id,
        created=str(job.created),
        updated=str(job.updated),
        completed_at=job.completed_at,
        items=[ImportJobItemResponse(**item.as_progress_dict()) for item in items],
    )


@router.post("/imports", response_model=ImportJobResponse)
async def create_import_job(
    notebooks: Optional[str] = Form(None),
    transformations: Optional[str] = Form(None),
    embed: str = Form("false"),
    delete_source: str = Form("false"),
    files: List[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    notebook_ids = _parse_json_list(notebooks, "notebooks")
    transformation_ids = _parse_json_list(transformations, "transformations")

    for notebook_id in notebook_ids:
        try:
            await Notebook.get(notebook_id)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    for transformation_id in transformation_ids:
        try:
            await Transformation.get(transformation_id)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    embed_bool = _str_to_bool(embed)
    delete_source_bool = _str_to_bool(delete_source)

    job = ImportJob(
        job_type="upload",
        status="queued",
        notebooks=notebook_ids,
        transformations=transformation_ids,
        embed=embed_bool,
        delete_source=delete_source_bool,
        total_items=sum(
            1 for upload_file in files if Path(upload_file.filename or "").suffix.lower() != ".zip"
        ),
        completed_items=0,
        failed_items=0,
    )
    await job.save()

    created_items: list[ImportJobItem] = []
    try:
        archive_root = Path(UPLOADS_FOLDER) / "import_archives" / (job.id or "job").replace(":", "_")
        archive_root.mkdir(parents=True, exist_ok=True)

        for sequence, upload_file in enumerate(files, start=1):
            filename = upload_file.filename or f"upload-{sequence}"
            is_archive = Path(filename).suffix.lower() == ".zip"
            target_dir = str(archive_root if is_archive else Path(UPLOADS_FOLDER))
            file_path = await _save_uploaded_file_stream(upload_file, target_dir)

            item = ImportJobItem(
                import_job_id=job.id or "",
                kind="archive" if is_archive else "file",
                status="queued",
                sequence=sequence,
                name=filename,
                display_name=filename,
                file_path=file_path,
            )
            await item.save()
            created_items.append(item)

        import commands.import_commands  # noqa: F401

        command_id = await CommandService.submit_command_job(
            "open_notebook",
            "process_import_job",
            {
                "import_job_id": job.id,
                "user_db_name": get_current_user_db(),
            },
        )
        job.command_id = command_id
        await job.save()
        return await _serialize_import_job(job)
    except Exception as e:
        logger.error(f"Failed to create import job: {e}")
        for item in created_items:
            try:
                Path(item.file_path).unlink(missing_ok=True)
            except Exception:
                pass
            try:
                await item.delete()
            except Exception:
                pass
        try:
            await job.delete()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create import job: {e}")


@router.get("/imports/{import_job_id}", response_model=ImportJobResponse)
async def get_import_job(import_job_id: str):
    try:
        job = await ImportJob.get(import_job_id)
        return await _serialize_import_job(job)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to fetch import job {import_job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch import job")
