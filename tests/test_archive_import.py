import zipfile
from pathlib import Path

import pytest

from api.routers import sources


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
