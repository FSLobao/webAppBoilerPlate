"""Tests of settings parsing and image format detection."""

from pathlib import Path

import pytest

from webapp_api.config import Settings, SettingsError
from webapp_api.images import ImageStore, detect_image_extension

ENV = {
    "WEBAPP_DB_HOST": "webapp-db",
    "WEBAPP_DB_NAME": "db_webapp",
    "WEBAPP_DB_USER": "webapp_api",
    "WEBAPP_DB_PASSWORD_FILE": "/run/secrets/api-db-password",
}


def test_settings_from_env_applies_defaults() -> None:
    settings = Settings.from_env(ENV)
    assert settings.db_port == 5432
    assert settings.images_dir == Path("/data/images")
    assert settings.files_url_prefix == "/webapp/files"


def test_settings_require_db_host() -> None:
    with pytest.raises(SettingsError, match="WEBAPP_DB_HOST"):
        Settings.from_env({**ENV, "WEBAPP_DB_HOST": " "})


def test_settings_reject_non_numeric_port() -> None:
    with pytest.raises(SettingsError):
        Settings.from_env({**ENV, "WEBAPP_DB_PORT": "abc"})


def test_conninfo_reads_password_file(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("s3cret\n", encoding="utf-8")
    settings = Settings.from_env({**ENV, "WEBAPP_DB_PASSWORD_FILE": str(secret)})
    assert "password=s3cret" in settings.conninfo()


def test_conninfo_rejects_empty_password_file(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("\n", encoding="utf-8")
    settings = Settings.from_env({**ENV, "WEBAPP_DB_PASSWORD_FILE": str(secret)})
    with pytest.raises(SettingsError):
        settings.conninfo()


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00", "png"),
        (b"\xff\xd8\xff\xe0\x00\x00\x00\x00\x00\x00\x00\x00", "jpg"),
        (b"GIF89a\x00\x00\x00\x00\x00\x00", "gif"),
        (b"RIFF\x00\x00\x00\x00WEBP", "webp"),
        (b"<svg xmlns=", None),
        (b"", None),
    ],
)
def test_detects_image_extension(header: bytes, expected: str | None) -> None:
    assert detect_image_extension(header) == expected


def test_delete_ignores_unexpected_names(tmp_path: Path) -> None:
    victim = tmp_path / "keep.txt"
    victim.write_text("x", encoding="utf-8")
    ImageStore(tmp_path, 10).delete("../keep.txt")
    assert victim.exists()
