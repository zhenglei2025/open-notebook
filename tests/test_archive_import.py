import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.routers import sources
from api.models import SourceCreate


def _write_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


class TestArchiveImport:
    def test_extract_archive_files_handles_nested_zip_and_folders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sources, "UPLOADS_FOLDER", str(tmp_path / "uploads"))

        nested_zip_path = tmp_path / "nested.zip"
        _write_zip(
            nested_zip_path,
            {
                "inner/slide.txt": b"nested slide",
            },
        )

        archive_path = tmp_path / "bundle.zip"
        _write_zip(
            archive_path,
            {
                "docs/report.txt": b"report body",
                "docs/nested.zip": nested_zip_path.read_bytes(),
            },
        )

        extracted = sources.extract_archive_files(str(archive_path))

        titles = sorted(item.display_title for item in extracted.files)
        assert titles == [
            "docs/nested/inner/slide.txt",
            "docs/report.txt",
        ]
        assert all(Path(item.file_path).exists() for item in extracted.files)

    def test_extract_archive_files_skips_hidden_and_unsafe_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sources, "UPLOADS_FOLDER", str(tmp_path / "uploads"))

        archive_path = tmp_path / "unsafe.zip"
        _write_zip(
            archive_path,
            {
                "../escape.txt": b"nope",
                "__MACOSX/._junk": b"skip",
                ".DS_Store": b"skip",
                "safe/keep.txt": b"ok",
            },
        )

        extracted = sources.extract_archive_files(str(archive_path))

        assert [item.display_title for item in extracted.files] == ["safe/keep.txt"]
        assert Path(extracted.files[0].file_path).read_text() == "ok"

    def test_extract_archive_files_handles_relative_upload_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        uploads_dir = tmp_path / "data" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sources, "UPLOADS_FOLDER", "data/uploads")

        archive_path = tmp_path / "relative.zip"
        _write_zip(
            archive_path,
            {
                "meeting_notes.docx": b"fake-docx",
            },
        )

        extracted = sources.extract_archive_files(str(archive_path))

        assert len(extracted.files) == 1
        assert extracted.files[0].display_title == "meeting_notes.docx"
        assert Path(extracted.files[0].file_path).is_absolute()

    @pytest.mark.asyncio
    async def test_create_archive_response_async_continues_after_single_file_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        failed_file = tmp_path / "failed.txt"
        failed_file.write_text("failed")
        success_file = tmp_path / "success.txt"
        success_file.write_text("success")
        archive_zip = tmp_path / "bundle.zip"
        archive_zip.write_bytes(b"zip")

        archive = sources.ExtractedArchive(
            root_dir=str(tmp_path / "archive"),
            files=[
                sources.ExtractedArchiveFile(
                    file_path=str(failed_file),
                    display_title="failed.txt",
                ),
                sources.ExtractedArchiveFile(
                    file_path=str(success_file),
                    display_title="success.txt",
                ),
            ],
        )
        source_data = SourceCreate(
            type="upload",
            notebooks=["notebook:test"],
            file_path="bundle.zip",
            embed=True,
            delete_source=False,
            async_processing=True,
        )

        cleanup_calls: list[str] = []

        async def fake_queue_archive_file_for_processing(*, extracted_file, **kwargs):
            if extracted_file.display_title == "failed.txt":
                raise RuntimeError(
                    "Failed to commit transaction due to a read or write conflict"
                )
            return (
                SimpleNamespace(
                    id="source:success",
                    title=extracted_file.display_title,
                    topics=[],
                    created="created",
                    updated="updated",
                ),
                "command:success",
            )

        monkeypatch.setattr(
            sources,
            "_queue_archive_file_for_processing",
            fake_queue_archive_file_for_processing,
        )
        monkeypatch.setattr(
            sources,
            "_delete_path_safely",
            lambda path: cleanup_calls.append(str(path)),
        )

        response = await sources._create_archive_response_async(
            source_data=source_data,
            archive=archive,
            transformation_ids=[],
            archive_path=str(archive_zip),
        )

        assert response.id == "source:success"
        assert response.command_id == "command:success"
        assert response.processing_info["archive_queued_sources_count"] == 1
        assert response.processing_info["archive_failed_sources_count"] == 1
        assert str(failed_file) in cleanup_calls
        assert str(archive_zip) in cleanup_calls

    @pytest.mark.asyncio
    async def test_queue_archive_file_retries_transaction_conflicts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        attempts = {"count": 0}
        sleep_calls: list[float] = []

        class FakeSource:
            def __init__(self):
                self.id = "source:retry"
                self.title = "retry.txt"
                self.topics = []
                self.created = "created"
                self.updated = "updated"
                self.deleted = 0
                self.asset = None

            async def save(self):
                return None

            async def delete(self):
                self.deleted += 1

        async def fake_create_pending_source(**kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError(
                    "The query was not executed due to a failed transaction. "
                    "Failed to commit transaction due to a read or write conflict. "
                    "This transaction can be retried"
                )
            return FakeSource()

        async def fake_submit_async_source_processing(**kwargs):
            return "command:retry"

        async def fake_sleep(delay: float):
            sleep_calls.append(delay)

        monkeypatch.setattr(
            sources, "_create_pending_source", fake_create_pending_source
        )
        monkeypatch.setattr(
            sources,
            "_submit_async_source_processing",
            fake_submit_async_source_processing,
        )
        monkeypatch.setattr(sources.asyncio, "sleep", fake_sleep)

        source_data = SourceCreate(
            type="upload",
            notebooks=["notebook:test"],
            file_path="retry.zip",
            embed=True,
            delete_source=False,
            async_processing=True,
        )
        extracted_file = sources.ExtractedArchiveFile(
            file_path="/tmp/retry.txt",
            display_title="retry.txt",
        )

        source, command_id = await sources._queue_archive_file_for_processing(
            extracted_file=extracted_file,
            source_data=source_data,
            transformation_ids=[],
        )

        assert attempts["count"] == 3
        assert command_id == "command:retry"
        assert source.id == "source:retry"
        assert sleep_calls == [0.2, 0.4]

    @pytest.mark.asyncio
    async def test_queue_archive_file_persists_asset_path_before_processing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        class FakeSource:
            def __init__(self):
                self.id = "source:file-path"
                self.title = "retry.txt"
                self.topics = []
                self.created = "created"
                self.updated = "updated"
                self.asset = None
                self.saved_assets: list[str | None] = []

            async def save(self):
                self.saved_assets.append(
                    self.asset.file_path if self.asset else None
                )

            async def delete(self):
                return None

        fake_source = FakeSource()

        async def fake_create_pending_source(**kwargs):
            return fake_source

        async def fake_submit_async_source_processing(*, source, **kwargs):
            assert source.asset is not None
            assert source.asset.file_path == "/tmp/retry.txt"
            return "command:file-path"

        monkeypatch.setattr(
            sources, "_create_pending_source", fake_create_pending_source
        )
        monkeypatch.setattr(
            sources,
            "_submit_async_source_processing",
            fake_submit_async_source_processing,
        )

        source_data = SourceCreate(
            type="upload",
            notebooks=["notebook:test"],
            file_path="retry.zip",
            embed=True,
            delete_source=False,
            async_processing=True,
        )
        extracted_file = sources.ExtractedArchiveFile(
            file_path="/tmp/retry.txt",
            display_title="retry.txt",
        )

        source, command_id = await sources._queue_archive_file_for_processing(
            extracted_file=extracted_file,
            source_data=source_data,
            transformation_ids=[],
        )

        assert command_id == "command:file-path"
        assert source is fake_source
        assert fake_source.saved_assets == ["/tmp/retry.txt"]

    @pytest.mark.asyncio
    async def test_retry_source_processing_uses_reference_edges_for_notebooks(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        class FakeAsset:
            file_path = "/tmp/retry.txt"
            url = None

        class FakeSource:
            def __init__(self):
                self.id = "source:test"
                self.title = "retry.txt"
                self.topics = []
                self.asset = FakeAsset()
                self.full_text = None
                self.created = "created"
                self.updated = "updated"
                self.command = None

            async def get_status(self):
                return "failed"

            async def save(self):
                return None

            async def get_embedded_chunks(self):
                return 0

        fake_source = FakeSource()

        async def fake_get(_source_id):
            return fake_source

        async def fake_repo_query(query, params):
            assert query == "SELECT VALUE out FROM reference WHERE in = $source_id"
            assert str(params["source_id"]) == "source:test"
            return ["notebook:abc"]

        async def fake_submit_command_job(*args, **kwargs):
            return "command:cmd123"

        monkeypatch.setattr(sources.Source, "get", fake_get)
        monkeypatch.setattr(sources, "repo_query", fake_repo_query)
        monkeypatch.setattr(
            sources.CommandService,
            "submit_command_job",
            fake_submit_command_job,
        )

        response = await sources.retry_source_processing("source:test")

        assert response.status == "queued"
        assert response.command_id == "command:cmd123"
        assert str(fake_source.command) == "command:cmd123"

    @pytest.mark.asyncio
    async def test_effective_source_status_reports_embedding_in_progress(self):
        class FakeSource:
            id = "source:embed"
            command = "command:process"
            embedding_command = "command:embed"

            async def get_status(self):
                return "completed"

            async def get_processing_progress(self):
                return {"status": "completed"}

            async def get_embedding_status(self):
                return "running"

            async def get_embedding_progress(self):
                return {"status": "running", "error": None}

            async def get_embedded_chunks(self):
                return 0

        status, processing_info, message = await sources._get_effective_source_status(
            FakeSource()
        )

        assert status == "embedding"
        assert processing_info["embedding_status"] == "running"
        assert processing_info["embedding_command_id"] == "command:embed"
        assert message == "Source embedding in progress"

    @pytest.mark.asyncio
    async def test_effective_source_status_reports_embedding_failure(self):
        class FakeSource:
            id = "source:embed"
            command = "command:process"
            embedding_command = "command:embed"

            async def get_status(self):
                return "completed"

            async def get_processing_progress(self):
                return {"status": "completed"}

            async def get_embedding_status(self):
                return "failed"

            async def get_embedding_progress(self):
                return {
                    "status": "failed",
                    "error": "Embedding provider timed out",
                }

            async def get_embedded_chunks(self):
                return 0

        status, processing_info, message = await sources._get_effective_source_status(
            FakeSource()
        )

        assert status == "failed"
        assert processing_info["embedding_error"] == "Embedding provider timed out"
        assert message == "Embedding provider timed out"

    def test_source_normalizes_enum_like_command_status_strings(self):
        source = sources.Source()

        assert source._normalize_command_status("CommandStatus.NEW") == "new"
        assert source._normalize_command_status("queued") == "queued"

        class FakeStatus:
            value = "CommandStatus.RUNNING"

        assert source._normalize_command_status(FakeStatus()) == "running"
