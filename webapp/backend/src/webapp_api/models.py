"""Request and response models of the webapp API.

Public API: :class:`UserIn`, :class:`UserOut` and :class:`HealthOut`.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from webapp_api.repository import UserRecord


class UserIn(BaseModel):
    """Editable user fields, sent when creating or updating a user."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]
    """Display name, 1 to 200 characters after trimming."""
    email: Annotated[EmailStr, Field(max_length=254)]
    """Email address; unique ignoring letter case."""
    location: Annotated[str | None, Field(max_length=200)] = None
    """Free-text location; empty text is stored as null."""

    @field_validator("location")
    @classmethod
    def _empty_location_is_none(cls, value: str | None) -> str | None:
        """Store an empty location as null."""
        return value or None


class UserOut(BaseModel):
    """User as returned by the API."""

    id: int
    """Database-generated identifier."""
    name: str
    """Display name."""
    email: str
    """Email address."""
    location: str | None
    """Free-text location, or null."""
    image_url: str | None
    """Absolute path of the profile image served by NGINX, or null."""
    created_at: datetime
    """Creation instant, ISO 8601 with offset."""
    updated_at: datetime
    """Last modification instant, ISO 8601 with offset."""

    @classmethod
    def from_record(cls, record: UserRecord, files_url_prefix: str) -> "UserOut":
        """Build the response model from a stored record.

        Args:
            record: Stored user.
            files_url_prefix: Public URL prefix of the images directory.

        Returns:
            Response model with ``image_url`` resolved.
        """
        image_url = (
            f"{files_url_prefix}/{record.image_file}" if record.image_file else None
        )
        return cls(
            id=record.id,
            name=record.name,
            email=record.email,
            location=record.location,
            image_url=image_url,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class HealthOut(BaseModel):
    """Health check result."""

    status: Literal["ok"]
    """Always ``ok`` when the database answers."""
