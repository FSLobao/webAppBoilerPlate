"""Profile image storage on the shared ``webapp-images`` volume.

Public API: :class:`ImageStore`, :func:`detect_image_extension` and the errors
:class:`ImageTooLargeError` and :class:`UnsupportedImageError`. NGINX serves the
stored files read-only; this module only writes and deletes them.
"""

import logging
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO, Final

logger = logging.getLogger(__name__)

_HEADER_BYTES: Final = 12
"""Bytes needed to identify every supported format."""

_CHUNK_BYTES: Final = 64 * 1024
"""Copy buffer size, in bytes."""

_FILE_NAME_PATTERN: Final = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
"""Stored file names; matches the database check constraint."""


class ImageTooLargeError(ValueError):
    """Raised when an upload exceeds the size limit."""


class UnsupportedImageError(ValueError):
    """Raised when the upload is not PNG, JPEG, GIF or WebP."""


def detect_image_extension(header: bytes) -> str | None:
    """Identify the image format from its first bytes.

    The client-supplied name and content type are ignored on purpose.

    Args:
        header: At least the first 12 bytes of the file.

    Returns:
        ``png``, ``jpg``, ``gif`` or ``webp``, or None when unsupported.
    """
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


class ImageStore:
    """Write and delete profile images in one directory.

    Files are named ``<random hex>.<ext>`` and written atomically: a temporary
    file is renamed only after the full upload passes validation.

    Args:
        directory: Existing writable directory.
        max_bytes: Largest accepted file size, in bytes.
    """

    def __init__(self, directory: Path, max_bytes: int) -> None:
        self._directory = directory
        self._max_bytes = max_bytes

    def save(self, source: BinaryIO) -> str:
        """Validate and store an uploaded image.

        Args:
            source: Readable binary stream positioned at the start.

        Returns:
            Stored file name.

        Raises:
            UnsupportedImageError: If the format is not supported.
            ImageTooLargeError: If the stream exceeds the size limit.
        """
        header = source.read(_HEADER_BYTES)
        extension = detect_image_extension(header)
        if extension is None:
            raise UnsupportedImageError
        name = f"{uuid.uuid4().hex}.{extension}"
        temporary = self._directory / f".upload-{name}"
        try:
            with temporary.open("xb") as target:
                written = len(header)
                target.write(header)
                while chunk := source.read(_CHUNK_BYTES):
                    written += len(chunk)
                    if written > self._max_bytes:
                        raise ImageTooLargeError
                    target.write(chunk)
            # NGINX workers run as another user and need read access.
            temporary.chmod(0o644)
            os.replace(temporary, self._directory / name)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return name

    def delete(self, name: str | None) -> None:
        """Remove a stored image; log and continue when removal fails.

        Args:
            name: Stored file name, or None to do nothing.
        """
        if name is None:
            return
        if not _FILE_NAME_PATTERN.fullmatch(name):
            logger.warning("Refusing to delete unexpected image name %r", name)
            return
        try:
            (self._directory / name).unlink(missing_ok=True)
        except OSError:
            logger.exception("Cannot delete image %s", name)
