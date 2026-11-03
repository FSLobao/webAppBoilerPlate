"""Persistence of user records in PostgreSQL.

Public API: :class:`UserRecord`, the :class:`UserRepository` protocol, its
PostgreSQL implementation :class:`PostgresUserRepository`, and the domain errors
:class:`UserNotFoundError` and :class:`DuplicateEmailError`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

from psycopg import errors
from psycopg_pool import ConnectionPool

# Every statement below returns the columns of _RETURNED, in UserRecord field order.

_SELECT_ALL: Final = (
    "SELECT ID_USUARIO, NO_USUARIO, ED_EMAIL, NO_LOCALIZACAO, NO_ARQUIVO_IMAGEM, "
    "DH_CRIACAO, DH_ATUALIZACAO FROM webapp.TB_USUARIO ORDER BY ID_USUARIO"
)
_SELECT_ONE: Final = (
    "SELECT ID_USUARIO, NO_USUARIO, ED_EMAIL, NO_LOCALIZACAO, NO_ARQUIVO_IMAGEM, "
    "DH_CRIACAO, DH_ATUALIZACAO FROM webapp.TB_USUARIO WHERE ID_USUARIO = %s"
)
_INSERT: Final = (
    "INSERT INTO webapp.TB_USUARIO (NO_USUARIO, ED_EMAIL, NO_LOCALIZACAO) "
    "VALUES (%s, %s, %s) RETURNING ID_USUARIO, NO_USUARIO, ED_EMAIL, "
    "NO_LOCALIZACAO, NO_ARQUIVO_IMAGEM, DH_CRIACAO, DH_ATUALIZACAO"
)
_UPDATE: Final = (
    "UPDATE webapp.TB_USUARIO SET NO_USUARIO = %s, ED_EMAIL = %s, "
    "NO_LOCALIZACAO = %s, DH_ATUALIZACAO = now() WHERE ID_USUARIO = %s "
    "RETURNING ID_USUARIO, NO_USUARIO, ED_EMAIL, NO_LOCALIZACAO, "
    "NO_ARQUIVO_IMAGEM, DH_CRIACAO, DH_ATUALIZACAO"
)
_DELETE: Final = (
    "DELETE FROM webapp.TB_USUARIO WHERE ID_USUARIO = %s "
    "RETURNING ID_USUARIO, NO_USUARIO, ED_EMAIL, NO_LOCALIZACAO, "
    "NO_ARQUIVO_IMAGEM, DH_CRIACAO, DH_ATUALIZACAO"
)
# The CTE locks the row and exposes the previous image name, so the caller can
# delete the old file only after the update commits.
_SET_IMAGE: Final = (
    "WITH OLD AS (SELECT ID_USUARIO, NO_ARQUIVO_IMAGEM "
    "FROM webapp.TB_USUARIO WHERE ID_USUARIO = %s FOR UPDATE) "
    "UPDATE webapp.TB_USUARIO AS U SET NO_ARQUIVO_IMAGEM = %s, "
    "DH_ATUALIZACAO = now() FROM OLD WHERE U.ID_USUARIO = OLD.ID_USUARIO "
    "RETURNING U.ID_USUARIO, U.NO_USUARIO, U.ED_EMAIL, U.NO_LOCALIZACAO, "
    "U.NO_ARQUIVO_IMAGEM, U.DH_CRIACAO, U.DH_ATUALIZACAO, OLD.NO_ARQUIVO_IMAGEM"
)


class UserNotFoundError(LookupError):
    """Raised when no user has the requested identifier."""


class DuplicateEmailError(ValueError):
    """Raised when another user already has the email, ignoring letter case."""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """One row of ``webapp.TB_USUARIO``.

    Attributes:
        id: Database-generated identifier.
        name: Display name.
        email: Email address.
        location: Free-text location, or None.
        image_file: Image file name in the images directory, or None.
        created_at: Creation instant (UTC-aware).
        updated_at: Last modification instant (UTC-aware).
    """

    id: int
    name: str
    email: str
    location: str | None
    image_file: str | None
    created_at: datetime
    updated_at: datetime


class UserRepository(Protocol):
    """Storage operations required by the API."""

    def ping(self) -> None:
        """Check that the storage answers; raise on failure."""

    def list_users(self) -> list[UserRecord]:
        """Return all users ordered by identifier."""

    def get_user(self, user_id: int) -> UserRecord:
        """Return one user or raise :class:`UserNotFoundError`."""

    def create_user(self, name: str, email: str, location: str | None) -> UserRecord:
        """Insert a user or raise :class:`DuplicateEmailError`."""

    def update_user(
        self, user_id: int, name: str, email: str, location: str | None
    ) -> UserRecord:
        """Replace the user fields; raise not-found or duplicate-email errors."""

    def delete_user(self, user_id: int) -> UserRecord:
        """Delete a user and return the deleted row, or raise not-found."""

    def set_image(
        self, user_id: int, image_file: str | None
    ) -> tuple[UserRecord, str | None]:
        """Set the image file name; return the updated row and the previous name."""


def _to_record(row: tuple[Any, ...]) -> UserRecord:
    """Convert a selected row tuple into a :class:`UserRecord`."""
    return UserRecord(*row)


class PostgresUserRepository:
    """User repository backed by a psycopg connection pool.

    Each method runs in its own transaction, committed when the pooled
    connection context exits without error.

    Args:
        pool: Open connection pool authenticated as the API role.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def ping(self) -> None:
        """Run a trivial query.

        Raises:
            psycopg.Error: If the database cannot be reached.
            psycopg_pool.PoolTimeout: If no connection is available in time.
        """
        with self._pool.connection() as conn:
            conn.execute("SELECT 1")

    def list_users(self) -> list[UserRecord]:
        """Return all users ordered by identifier."""
        with self._pool.connection() as conn:
            rows = conn.execute(_SELECT_ALL).fetchall()
        return [_to_record(row) for row in rows]

    def get_user(self, user_id: int) -> UserRecord:
        """Return one user.

        Raises:
            UserNotFoundError: If the user does not exist.
        """
        with self._pool.connection() as conn:
            row = conn.execute(
                _SELECT_ONE,
                (user_id,),
            ).fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        return _to_record(row)

    def create_user(self, name: str, email: str, location: str | None) -> UserRecord:
        """Insert a user.

        Raises:
            DuplicateEmailError: If the email is already registered.
        """
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    _INSERT,
                    (name, email, location),
                ).fetchone()
        except errors.UniqueViolation as err:
            raise DuplicateEmailError(email) from err
        if row is None:
            raise RuntimeError("INSERT returned no row")
        return _to_record(row)

    def update_user(
        self, user_id: int, name: str, email: str, location: str | None
    ) -> UserRecord:
        """Replace name, email and location.

        Raises:
            UserNotFoundError: If the user does not exist.
            DuplicateEmailError: If another user has the email.
        """
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    _UPDATE,
                    (name, email, location, user_id),
                ).fetchone()
        except errors.UniqueViolation as err:
            raise DuplicateEmailError(email) from err
        if row is None:
            raise UserNotFoundError(user_id)
        return _to_record(row)

    def delete_user(self, user_id: int) -> UserRecord:
        """Delete a user and return the deleted row.

        Raises:
            UserNotFoundError: If the user does not exist.
        """
        with self._pool.connection() as conn:
            row = conn.execute(
                _DELETE,
                (user_id,),
            ).fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        return _to_record(row)

    def set_image(
        self, user_id: int, image_file: str | None
    ) -> tuple[UserRecord, str | None]:
        """Set or clear the image file name, locking the row to read the old one.

        Returns:
            The updated user and the previous image file name, or None.

        Raises:
            UserNotFoundError: If the user does not exist.
        """
        with self._pool.connection() as conn:
            row = conn.execute(
                _SET_IMAGE,
                (user_id, image_file),
            ).fetchone()
        if row is None:
            raise UserNotFoundError(user_id)
        return _to_record(row[:-1]), row[-1]
