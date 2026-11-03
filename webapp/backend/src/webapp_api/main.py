"""FastAPI application: user CRUD API and SPA assets.

The API lives under ``/webapp/api`` and the static SPA under ``/webapp/``.

Public API: :func:`create_app`. Run with
``uvicorn webapp_api.main:create_app --factory``. Without injected dependencies,
the app reads :class:`~webapp_api.config.Settings` from the environment and opens a
PostgreSQL connection pool during startup.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool, PoolTimeout

from webapp_api.config import Settings
from webapp_api.images import ImageStore, ImageTooLargeError, UnsupportedImageError
from webapp_api.models import HealthOut, UserIn, UserOut
from webapp_api.repository import (
    DuplicateEmailError,
    PostgresUserRepository,
    UserNotFoundError,
    UserRepository,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/webapp/api"
"""Path prefix of every API route; NGINX forwards it unchanged."""

SPA_PREFIX = "/webapp"
"""Mount point of the static SPA assets."""


def _repository(request: Request) -> UserRepository:
    """Return the repository stored in the application state."""
    return request.app.state.repository


def _image_store(request: Request) -> ImageStore:
    """Return the image store stored in the application state."""
    return request.app.state.image_store


def _settings(request: Request) -> Settings:
    """Return the settings stored in the application state."""
    return request.app.state.settings


RepositoryDep = Annotated[UserRepository, Depends(_repository)]
ImageStoreDep = Annotated[ImageStore, Depends(_image_store)]
SettingsDep = Annotated[Settings, Depends(_settings)]

router = APIRouter(prefix=API_PREFIX)


@router.get("/health", summary="Check API and database health")
def health(repository: RepositoryDep) -> HealthOut:
    """Return ``ok`` when the database answers, otherwise HTTP 503."""
    try:
        repository.ping()
    except (psycopg.Error, PoolTimeout) as err:
        logger.warning("Database health check failed: %s", type(err).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable"
        ) from err
    return HealthOut(status="ok")


@router.get("/users", summary="List all users")
def list_users(repository: RepositoryDep, settings: SettingsDep) -> list[UserOut]:
    """Return every user ordered by identifier."""
    return [
        UserOut.from_record(record, settings.files_url_prefix)
        for record in repository.list_users()
    ]


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses={409: {"description": "Email already registered"}},
)
def create_user(
    user: UserIn, repository: RepositoryDep, settings: SettingsDep
) -> UserOut:
    """Create a user without image."""
    record = repository.create_user(user.name, user.email, user.location)
    return UserOut.from_record(record, settings.files_url_prefix)


@router.get(
    "/users/{user_id}",
    summary="Get one user",
    responses={404: {"description": "User not found"}},
)
def get_user(user_id: int, repository: RepositoryDep, settings: SettingsDep) -> UserOut:
    """Return one user."""
    return UserOut.from_record(repository.get_user(user_id), settings.files_url_prefix)


@router.put(
    "/users/{user_id}",
    summary="Update a user",
    responses={
        404: {"description": "User not found"},
        409: {"description": "Email already registered"},
    },
)
def update_user(
    user_id: int, user: UserIn, repository: RepositoryDep, settings: SettingsDep
) -> UserOut:
    """Replace name, email and location; the image is not changed."""
    record = repository.update_user(user_id, user.name, user.email, user.location)
    return UserOut.from_record(record, settings.files_url_prefix)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user and its image",
    responses={404: {"description": "User not found"}},
)
def delete_user(user_id: int, repository: RepositoryDep, store: ImageStoreDep) -> None:
    """Delete a user, then remove its image file."""
    record = repository.delete_user(user_id)
    store.delete(record.image_file)


@router.put(
    "/users/{user_id}/image",
    summary="Upload or replace the profile image",
    responses={
        404: {"description": "User not found"},
        413: {"description": "Image larger than the limit"},
        415: {"description": "Not a PNG, JPEG, GIF or WebP image"},
    },
)
def upload_image(
    user_id: int,
    file: UploadFile,
    repository: RepositoryDep,
    store: ImageStoreDep,
    settings: SettingsDep,
) -> UserOut:
    """Store a multipart image (field ``file``) and link it to the user.

    The format is detected from the file content. The previous image is removed
    after the database update succeeds.
    """
    repository.get_user(user_id)
    try:
        name = store.save(file.file)
    except UnsupportedImageError as err:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported image format"
        ) from err
    except ImageTooLargeError as err:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Image larger than {settings.max_image_bytes} bytes",
        ) from err
    try:
        record, previous = repository.set_image(user_id, name)
    except BaseException:
        store.delete(name)
        raise
    store.delete(previous)
    return UserOut.from_record(record, settings.files_url_prefix)


@router.delete(
    "/users/{user_id}/image",
    summary="Remove the profile image",
    responses={404: {"description": "User not found"}},
)
def delete_image(
    user_id: int, repository: RepositoryDep, store: ImageStoreDep, settings: SettingsDep
) -> UserOut:
    """Unlink the image from the user and remove its file."""
    record, previous = repository.set_image(user_id, None)
    store.delete(previous)
    return UserOut.from_record(record, settings.files_url_prefix)


def _not_found(_request: Request, _exc: Exception) -> JSONResponse:
    """Map :class:`UserNotFoundError` to HTTP 404."""
    return JSONResponse({"detail": "User not found"}, status.HTTP_404_NOT_FOUND)


def _duplicate_email(_request: Request, _exc: Exception) -> JSONResponse:
    """Map :class:`DuplicateEmailError` to HTTP 409."""
    return JSONResponse(
        {"detail": "Email already registered"}, status.HTTP_409_CONFLICT
    )


def create_app(
    settings: Settings | None = None,
    repository: UserRepository | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Settings to use; read from ``os.environ`` when None.
        repository: Repository to use; when None, a PostgreSQL pool is opened at
            startup and closed at shutdown.

    Returns:
        Configured application.
    """
    resolved = settings or Settings.from_env(os.environ)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if repository is not None:
            app.state.repository = repository
            yield
            return
        # wait=False lets the API start before the database is ready; requests
        # then fail fast with 503 or 5xx instead of blocking startup.
        pool = ConnectionPool(
            resolved.conninfo(), min_size=1, max_size=5, timeout=5, open=False
        )
        pool.open(wait=False)
        app.state.repository = PostgresUserRepository(pool)
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(
        title="webapp API",
        summary="CRUD of users with profile images.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = resolved
    app.state.image_store = ImageStore(resolved.images_dir, resolved.max_image_bytes)
    app.add_exception_handler(UserNotFoundError, _not_found)
    app.add_exception_handler(DuplicateEmailError, _duplicate_email)
    app.include_router(router)
    if resolved.static_dir.is_dir():
        app.mount(
            SPA_PREFIX,
            StaticFiles(directory=resolved.static_dir, html=True),
            name="spa",
        )
    else:
        logger.warning(
            "Static directory %s not found; SPA disabled", resolved.static_dir
        )
    return app
