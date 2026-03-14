"""API router for PPT generation tasks."""

from fastapi import APIRouter
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel
from typing import Optional
from urllib.parse import quote

from surreal_commands import submit_command

from open_notebook.database.repository import ensure_record_id, get_current_user_db
from open_notebook.domain.note_ppt import NotePpt
from open_notebook.domain.notebook import Note
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


class GeneratePptRequest(BaseModel):
    user_prompt: Optional[str] = None


class NotePptResponse(BaseModel):
    id: str
    note: str
    title: str
    status: str
    error_message: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None


# ─── POST /notes/{note_id}/generate-ppt ───────────────────────────────────────

@router.post("/notes/{note_id}/generate-ppt", response_model=NotePptResponse)
async def generate_ppt(note_id: str, body: GeneratePptRequest):
    """Submit a PPT generation task for a note."""
    # Ensure prefix
    if not note_id.startswith("note:"):
        note_id = f"note:{note_id}"

    # Load note
    note = await Note.get(note_id)
    if not note:
        raise NotFoundError(f"Note {note_id} not found")
    if not note.content or not note.content.strip():
        raise InvalidInputError("Note has no content to generate PPT from")

    # Determine sequential title
    existing_count = await NotePpt.count_by_note(note_id)
    seq = existing_count + 1
    note_title = note.title or "Untitled"
    ppt_title = f"{note_title} #{seq}"

    # Create note_ppt record
    ppt = NotePpt(
        note=note_id,
        title=ppt_title,
        user_prompt=body.user_prompt,
        status="queued",
    )
    await ppt.save()

    logger.info(f"Created PPT task {ppt.id} for note {note_id}: {ppt_title}")

    # Submit async command
    command_id = submit_command(
        "open_notebook",
        "generate_ppt",
        {
            "note_ppt_id": str(ppt.id),
            "note_content": note.content,
            "note_title": note_title,
            "user_prompt": body.user_prompt or "",
            "user_db_name": get_current_user_db(),
        },
    )
    logger.info(f"Submitted generate_ppt command {command_id} for {ppt.id}")

    return NotePptResponse(
        id=str(ppt.id),
        note=note_id,
        title=ppt_title,
        status="queued",
        created=str(ppt.created) if ppt.created else None,
        updated=str(ppt.updated) if ppt.updated else None,
    )


# ─── GET /notes/{note_id}/ppt-tasks ───────────────────────────────────────────

@router.get("/notes/{note_id}/ppt-tasks", response_model=list[NotePptResponse])
async def list_ppt_tasks(note_id: str):
    """List all PPT tasks for a note."""
    if not note_id.startswith("note:"):
        note_id = f"note:{note_id}"

    tasks = await NotePpt.get_by_note(note_id)
    return [
        NotePptResponse(
            id=str(t.id),
            note=str(t.note),
            title=t.title,
            status=t.status,
            error_message=t.error_message,
            created=str(t.created) if t.created else None,
            updated=str(t.updated) if t.updated else None,
        )
        for t in tasks
    ]


# ─── GET /notes/ppt/{ppt_id}/download ─────────────────────────────────────────

@router.get("/notes/ppt/{ppt_id}/download")
async def download_ppt(ppt_id: str):
    """Download the generated PPTX file."""
    import base64

    if not ppt_id.startswith("note_ppt:"):
        ppt_id = f"note_ppt:{ppt_id}"

    ppt = await NotePpt.get(ppt_id)
    if not ppt:
        raise NotFoundError(f"PPT task {ppt_id} not found")
    if ppt.status != "completed" or not ppt.pptx_data:
        raise InvalidInputError("PPT is not ready for download")

    pptx_bytes = base64.b64decode(ppt.pptx_data)
    filename = f"{ppt.title}.pptx"
    encoded = quote(filename)
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f"attachment; filename=\"presentation.pptx\"; filename*=UTF-8''{encoded}"
        },
    )


# ─── DELETE /notes/ppt/{ppt_id} ───────────────────────────────────────────────

@router.delete("/notes/ppt/{ppt_id}")
async def delete_ppt(ppt_id: str):
    """Delete a PPT task."""
    if not ppt_id.startswith("note_ppt:"):
        ppt_id = f"note_ppt:{ppt_id}"

    ppt = await NotePpt.get(ppt_id)
    if not ppt:
        raise NotFoundError(f"PPT task {ppt_id} not found")

    await ppt.delete()
    return {"success": True}
