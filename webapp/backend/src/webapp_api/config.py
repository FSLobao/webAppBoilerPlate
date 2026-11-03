"""Runtime settings for the webapp API, read from environment variables.

Public API: :class:`Settings` and :class:`SettingsError`. Reading the database
password file happens only when :meth:`Settings.conninfo` is called.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from psycopg.conninfo import make_conninfo

DEFAULT_MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
"""Largest accepted profile image, in bytes (5 MiB)."""


class SettingsError(ValueError):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Settings of one API process.

    Attributes:
        db_host: PostgreSQL host name on the Podman network.
        db_port: PostgreSQL TCP port.
        db_name: Database name.
        db_user: Login role of the API (least privilege).
        db_password_file: File holding the role password, mounted read-only.
        images_dir: Writable directory where profile images are stored.
        static_dir: Directory with the SPA assets, served under ``/webapp/``.
        files_url_prefix: Public URL prefix that NGINX maps to ``images_dir``.
        max_image_bytes: Largest accepted image upload, in bytes.
    """

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password_file: Path
    images_dir: Path
    static_dir: Path
    files_url_prefix: str = "/webapp/files"
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Build settings from ``WEBAPP_*`` environment variables.

        Args:
            env: Environment mapping, usually ``os.environ``.

        Returns:
            Validated settings.

        Raises:
            SettingsError: If a required variable is missing or a number is invalid.
        """

        def required(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise SettingsError(f"Missing required environment variable {name}")
            return value

        try:
            db_port = int(env.get("WEBAPP_DB_PORT", "5432"))
            max_image_bytes = int(
                env.get("WEBAPP_MAX_IMAGE_BYTES", str(DEFAULT_MAX_IMAGE_BYTES))
            )
        except ValueError as err:
            raise SettingsError(
                "WEBAPP_DB_PORT and WEBAPP_MAX_IMAGE_BYTES must be integers"
            ) from err

        return cls(
            db_host=required("WEBAPP_DB_HOST"),
            db_port=db_port,
            db_name=required("WEBAPP_DB_NAME"),
            db_user=required("WEBAPP_DB_USER"),
            db_password_file=Path(required("WEBAPP_DB_PASSWORD_FILE")),
            images_dir=Path(env.get("WEBAPP_IMAGES_DIR", "/data/images")),
            static_dir=Path(env.get("WEBAPP_STATIC_DIR", "/app/frontend")),
            files_url_prefix=env.get("WEBAPP_FILES_URL_PREFIX", "/webapp/files").rstrip(
                "/"
            ),
            max_image_bytes=max_image_bytes,
        )

    def conninfo(self) -> str:
        """Return the libpq connection string, reading the password file.

        Returns:
            Connection string including the password; never log it.

        Raises:
            SettingsError: If the password file cannot be read or is empty.
        """
        try:
            password = self.db_password_file.read_text(encoding="utf-8").strip()
        except OSError as err:
            raise SettingsError(f"Cannot read {self.db_password_file}") from err
        if not password:
            raise SettingsError(f"Password file {self.db_password_file} is empty")
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=password,
            application_name="webapp-api",
        )
