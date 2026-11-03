"""Shared fixtures: in-memory repository and a test client without PostgreSQL."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_api.config import Settings
from webapp_api.main import create_app
from webapp_api.repository import DuplicateEmailError, UserNotFoundError, UserRecord

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class FakeUserRepository:
    """In-memory implementation of the UserRepository protocol."""

    def __init__(self) -> None:
        self.users: dict[int, UserRecord] = {}
        self._next_id = 1
        self.fail_set_image = False

    def ping(self) -> None:
        return None

    def list_users(self) -> list[UserRecord]:
        return [self.users[key] for key in sorted(self.users)]

    def get_user(self, user_id: int) -> UserRecord:
        try:
            return self.users[user_id]
        except KeyError:
            raise UserNotFoundError(user_id) from None

    def _check_email(self, email: str, user_id: int | None) -> None:
        for record in self.users.values():
            if record.email.lower() == email.lower() and record.id != user_id:
                raise DuplicateEmailError(email)

    def create_user(self, name: str, email: str, location: str | None) -> UserRecord:
        self._check_email(email, None)
        record = UserRecord(
            self._next_id, name, email, location, None, FIXED_NOW, FIXED_NOW
        )
        self.users[record.id] = record
        self._next_id += 1
        return record

    def update_user(
        self, user_id: int, name: str, email: str, location: str | None
    ) -> UserRecord:
        current = self.get_user(user_id)
        self._check_email(email, user_id)
        record = replace(current, name=name, email=email, location=location)
        self.users[user_id] = record
        return record

    def delete_user(self, user_id: int) -> UserRecord:
        record = self.get_user(user_id)
        del self.users[user_id]
        return record

    def set_image(
        self, user_id: int, image_file: str | None
    ) -> tuple[UserRecord, str | None]:
        current = self.get_user(user_id)
        if self.fail_set_image:
            raise RuntimeError("simulated database failure")
        record = replace(current, image_file=image_file)
        self.users[user_id] = record
        return record, current.image_file


@pytest.fixture
def images_dir(tmp_path: Path) -> Path:
    path = tmp_path / "images"
    path.mkdir()
    return path


@pytest.fixture
def repository() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def client(
    tmp_path: Path, images_dir: Path, repository: FakeUserRepository
) -> Iterator[TestClient]:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>spa</h1>", encoding="utf-8")
    settings = Settings(
        db_host="unused",
        db_port=5432,
        db_name="unused",
        db_user="unused",
        db_password_file=tmp_path / "unused",
        images_dir=images_dir,
        static_dir=static_dir,
        max_image_bytes=1024,
    )
    with TestClient(create_app(settings, repository)) as test_client:
        yield test_client
