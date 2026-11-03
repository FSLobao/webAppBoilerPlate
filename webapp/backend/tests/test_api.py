"""Behavior tests of the HTTP API using the in-memory repository."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeUserRepository

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
USERS = "/webapp/api/users"


def _create(client: TestClient, email: str = "ana@example.com") -> dict:
    response = client.post(
        USERS, json={"name": " Ana ", "email": email, "location": "Brasília"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_reports_ok(client: TestClient) -> None:
    assert client.get("/webapp/api/health").json() == {"status": "ok"}


def test_serves_spa_index(client: TestClient) -> None:
    response = client.get("/webapp/index.html")
    assert response.status_code == 200
    assert "spa" in response.text
    assert client.get("/webapp/").status_code == 200


def test_create_trims_name_and_returns_user(client: TestClient) -> None:
    user = _create(client)
    assert user["id"] == 1
    assert user["name"] == "Ana"
    assert user["location"] == "Brasília"
    assert user["image_url"] is None


def test_empty_location_is_stored_as_null(client: TestClient) -> None:
    response = client.post(
        USERS, json={"name": "Bia", "email": "bia@example.com", "location": "  "}
    )
    assert response.json()["location"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "email": "a@example.com"},
        {"name": "A", "email": "not-an-email"},
        {"name": "A" * 201, "email": "a@example.com"},
        {"name": "A", "email": "a@example.com", "location": "x" * 201},
        {"name": "A", "email": "a@example.com", "extra": 1},
        {"email": "a@example.com"},
    ],
)
def test_rejects_invalid_payload(client: TestClient, payload: dict) -> None:
    assert client.post(USERS, json=payload).status_code == 422


def test_rejects_duplicate_email_ignoring_case(client: TestClient) -> None:
    _create(client)
    response = client.post(USERS, json={"name": "B", "email": "ANA@example.com"})
    assert response.status_code == 409


def test_lists_users_in_id_order(client: TestClient) -> None:
    _create(client, "a@example.com")
    _create(client, "b@example.com")
    assert [u["id"] for u in client.get(USERS).json()] == [1, 2]


def test_update_replaces_fields(client: TestClient) -> None:
    user = _create(client)
    response = client.put(
        f"{USERS}/{user['id']}", json={"name": "Ana Maria", "email": "ana@example.com"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Ana Maria"
    assert response.json()["location"] is None


def test_update_unknown_user_returns_404(client: TestClient) -> None:
    response = client.put(f"{USERS}/99", json={"name": "X", "email": "x@example.com"})
    assert response.status_code == 404


def test_get_unknown_user_returns_404(client: TestClient) -> None:
    assert client.get(f"{USERS}/99").status_code == 404


def test_upload_stores_image_and_returns_url(
    client: TestClient, images_dir: Path
) -> None:
    user = _create(client)
    response = client.put(
        f"{USERS}/{user['id']}/image",
        files={"file": ("photo.bin", PNG, "application/octet-stream")},
    )
    assert response.status_code == 200
    url = response.json()["image_url"]
    assert url.startswith("/webapp/files/")
    assert url.endswith(".png")
    stored = images_dir / url.rsplit("/", 1)[1]
    assert stored.read_bytes() == PNG
    assert stored.stat().st_mode & 0o777 == 0o644


def test_replacing_image_removes_previous_file(
    client: TestClient, images_dir: Path
) -> None:
    user = _create(client)
    client.put(f"{USERS}/{user['id']}/image", files={"file": ("a", PNG)})
    client.put(f"{USERS}/{user['id']}/image", files={"file": ("b", JPEG)})
    assert [p.suffix for p in images_dir.iterdir()] == [".jpg"]


def test_rejects_unsupported_image(client: TestClient, images_dir: Path) -> None:
    user = _create(client)
    response = client.put(
        f"{USERS}/{user['id']}/image", files={"file": ("x.png", b"<svg></svg>")}
    )
    assert response.status_code == 415
    assert list(images_dir.iterdir()) == []


def test_rejects_too_large_image(client: TestClient, images_dir: Path) -> None:
    user = _create(client)
    response = client.put(
        f"{USERS}/{user['id']}/image", files={"file": ("big", PNG + b"\x00" * 2048)}
    )
    assert response.status_code == 413
    assert list(images_dir.iterdir()) == []


def test_upload_for_unknown_user_stores_nothing(
    client: TestClient, images_dir: Path
) -> None:
    response = client.put(f"{USERS}/99/image", files={"file": ("a", PNG)})
    assert response.status_code == 404
    assert list(images_dir.iterdir()) == []


def test_upload_removes_new_file_when_database_fails(
    client: TestClient, images_dir: Path, repository: FakeUserRepository
) -> None:
    user = _create(client)
    repository.fail_set_image = True
    with pytest.raises(RuntimeError):
        client.put(f"{USERS}/{user['id']}/image", files={"file": ("a", PNG)})
    assert list(images_dir.iterdir()) == []


def test_delete_image_clears_url_and_file(client: TestClient, images_dir: Path) -> None:
    user = _create(client)
    client.put(f"{USERS}/{user['id']}/image", files={"file": ("a", PNG)})
    response = client.delete(f"{USERS}/{user['id']}/image")
    assert response.status_code == 200
    assert response.json()["image_url"] is None
    assert list(images_dir.iterdir()) == []


def test_delete_user_removes_record_and_image(
    client: TestClient, images_dir: Path
) -> None:
    user = _create(client)
    client.put(f"{USERS}/{user['id']}/image", files={"file": ("a", PNG)})
    assert client.delete(f"{USERS}/{user['id']}").status_code == 204
    assert client.get(f"{USERS}/{user['id']}").status_code == 404
    assert list(images_dir.iterdir()) == []


def test_delete_unknown_user_returns_404(client: TestClient) -> None:
    assert client.delete(f"{USERS}/99").status_code == 404
