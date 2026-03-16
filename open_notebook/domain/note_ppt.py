import hashlib
import os
from typing import ClassVar, List, Optional

from loguru import logger
from pydantic import ConfigDict

from open_notebook.database.repository import repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError

# PPT files stored on disk instead of in the database
PPT_STORAGE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "ppt_files"
))
os.makedirs(PPT_STORAGE_DIR, exist_ok=True)


class NotePpt(ObjectModel):
    """Represents a PPT generation task linked to a note."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    table_name: ClassVar[str] = "note_ppt"
    note: str  # note ID (e.g. "note:xxx")
    title: str  # "{note_title} #{seq}"
    content: Optional[str] = None  # generated JSON (slide structure)
    pptx_path: Optional[str] = None  # filesystem path to .pptx file
    user_prompt: Optional[str] = None  # user's extra requirements
    status: str = "queued"  # queued | running | completed | failed
    error_message: Optional[str] = None

    @classmethod
    async def get_by_note(cls, note_id: str) -> List["NotePpt"]:
        """Get all PPT tasks for a given note (metadata only, no content blob)."""
        try:
            results = await repo_query(
                "SELECT id, note, title, pptx_path, user_prompt, status, "
                "error_message, created, updated "
                "FROM note_ppt WHERE note = $note_id ORDER BY created ASC",
                {"note_id": note_id},
            )
            return [cls(**r) for r in results] if results else []
        except Exception as e:
            logger.error(f"Error fetching PPT tasks for note {note_id}: {e}")
            raise DatabaseOperationError(e)

    @staticmethod
    def make_pptx_path(note_id: str, title: str) -> str:
        """Generate a unique filesystem path for a PPTX file."""
        hash_input = f"{note_id}:{title}"
        file_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return os.path.join(PPT_STORAGE_DIR, f"{file_hash}.pptx")

    def save_pptx_file(self, pptx_bytes: bytes) -> str:
        """Save PPTX bytes to disk and return the path."""
        path = self.make_pptx_path(self.note, self.title)
        with open(path, "wb") as f:
            f.write(pptx_bytes)
        self.pptx_path = path
        logger.info(f"Saved PPTX to {path} ({len(pptx_bytes)} bytes)")
        return path

    def delete_pptx_file(self):
        """Delete the PPTX file from disk."""
        if self.pptx_path and os.path.exists(self.pptx_path):
            os.remove(self.pptx_path)
            logger.info(f"Deleted PPTX file {self.pptx_path}")

    @classmethod
    async def max_seq_by_note(cls, note_id: str) -> int:
        """Get the maximum sequence number from existing PPT titles for a note.

        Looks at '#N' suffixes in titles to avoid reusing numbers after deletions.
        """
        try:
            results = await repo_query(
                "SELECT title FROM note_ppt WHERE note = $note_id",
                {"note_id": note_id},
            )
            max_seq = 0
            for row in results:
                title = row.get("title", "")
                if "#" in title:
                    try:
                        seq = int(title.rsplit("#", 1)[-1].strip())
                        max_seq = max(max_seq, seq)
                    except (ValueError, IndexError):
                        pass
            return max_seq
        except Exception as e:
            logger.error(f"Error getting max seq for note {note_id}: {e}")
            return 0
