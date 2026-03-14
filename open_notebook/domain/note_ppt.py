from typing import ClassVar, List, Optional

from loguru import logger
from pydantic import ConfigDict

from open_notebook.database.repository import repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError


class NotePpt(ObjectModel):
    """Represents a PPT generation task linked to a note."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    table_name: ClassVar[str] = "note_ppt"
    note: str  # note ID (e.g. "note:xxx")
    title: str  # "{note_title} #{seq}"
    content: Optional[str] = None  # generated JSON (slide structure)
    pptx_data: Optional[str] = None  # base64-encoded .pptx file
    user_prompt: Optional[str] = None  # user's extra requirements
    status: str = "queued"  # queued | running | completed | failed
    error_message: Optional[str] = None

    @classmethod
    async def get_by_note(cls, note_id: str) -> List["NotePpt"]:
        """Get all PPT tasks for a given note, ordered by creation time."""
        try:
            results = await repo_query(
                "SELECT * FROM note_ppt WHERE note = $note_id ORDER BY created ASC",
                {"note_id": note_id},
            )
            return [cls(**r) for r in results] if results else []
        except Exception as e:
            logger.error(f"Error fetching PPT tasks for note {note_id}: {e}")
            raise DatabaseOperationError(e)

    @classmethod
    async def count_by_note(cls, note_id: str) -> int:
        """Count existing PPT tasks for a note (for sequential numbering)."""
        try:
            results = await repo_query(
                "SELECT count() AS cnt FROM note_ppt WHERE note = $note_id GROUP ALL",
                {"note_id": note_id},
            )
            return results[0]["cnt"] if results else 0
        except Exception as e:
            logger.error(f"Error counting PPT tasks for note {note_id}: {e}")
            return 0
