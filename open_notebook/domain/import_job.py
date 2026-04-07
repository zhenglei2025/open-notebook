from typing import Any, ClassVar, Dict, List, Literal, Optional

from surrealdb import RecordID

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel
from pydantic import field_validator


ImportJobStatus = Literal[
    "queued",
    "running",
    "extracting",
    "completed",
    "partial_failed",
    "failed",
]

ImportJobItemStatus = Literal[
    "queued",
    "extracting",
    "processing",
    "completed",
    "failed",
]

ImportJobItemKind = Literal["file", "archive"]


class ImportJob(ObjectModel):
    table_name: ClassVar[str] = "import_job"
    nullable_fields: ClassVar[set[str]] = {
        "command_id",
        "current_item",
        "error_message",
        "completed_at",
    }

    job_type: Literal["upload"] = "upload"
    status: ImportJobStatus = "queued"
    notebooks: List[str] = []
    transformations: List[str] = []
    embed: bool = False
    delete_source: bool = False
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    current_item: Optional[str] = None
    error_message: Optional[str] = None
    command_id: Optional[str] = None
    completed_at: Optional[str] = None

    async def get_items(self) -> List["ImportJobItem"]:
        if not self.id:
            return []

        result = await repo_query(
            """
            SELECT *
            FROM import_job_item
            WHERE import_job_id = $job_id
            ORDER BY sequence ASC
            """,
            {"job_id": ensure_record_id(self.id)},
        )
        return [ImportJobItem(**row) for row in result] if result else []


class ImportJobItem(ObjectModel):
    table_name: ClassVar[str] = "import_job_item"
    nullable_fields: ClassVar[set[str]] = {
        "parent_item_id",
        "source_id",
        "error_message",
    }

    import_job_id: str
    parent_item_id: Optional[str] = None
    kind: ImportJobItemKind = "file"
    status: ImportJobItemStatus = "queued"
    sequence: int = 0
    name: str
    display_name: str
    file_path: str
    source_id: Optional[str] = None
    error_message: Optional[str] = None

    @field_validator("import_job_id", "parent_item_id", "source_id", mode="before")
    @classmethod
    def parse_record_ids(cls, value):
        if value is None:
            return None
        if isinstance(value, RecordID):
            return str(value)
        return str(value)

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        data["import_job_id"] = ensure_record_id(data["import_job_id"])
        if data.get("parent_item_id"):
            data["parent_item_id"] = ensure_record_id(data["parent_item_id"])
        if data.get("source_id"):
            data["source_id"] = ensure_record_id(data["source_id"])
        return data

    def as_progress_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parent_item_id": self.parent_item_id,
            "kind": self.kind,
            "status": self.status,
            "sequence": self.sequence,
            "name": self.name,
            "display_name": self.display_name,
            "file_path": self.file_path,
            "source_id": self.source_id,
            "error_message": self.error_message,
            "created": str(self.created) if self.created else None,
            "updated": str(self.updated) if self.updated else None,
        }
