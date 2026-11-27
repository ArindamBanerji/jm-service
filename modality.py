"""Project modality capability and locking policy.

Database-valid pairs are deliberately broader than the release switches.  The
database protects durable invariants; environment flags control which new
strict projects may be created or enabled by the running release.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit
from typing import Final

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Domain, LabelLog


VALID_CONTENT_TYPES: Final = frozenset({"text", "image"})
VALID_LABEL_SCHEMAS: Final = frozenset({"single", "multi", "ner"})
VALID_COMBINATIONS: Final = frozenset({
    ("text", "single"),
    ("text", "multi"),
    ("text", "ner"),
    ("image", "single"),
    ("image", "multi"),
})


MAX_INLINE = 10 * 1024 * 1024
_FORMATS = {"jpg", "jpeg", "png", "webp", "gif"}
_DATA_PREFIX = re.compile(r"data:image/(png|jpeg|gif|webp);base64,")
_SIGNATURES = {"png": (b"\x89PNG\r\n\x1a\n",), "jpeg": (b"\xff\xd8",),
               "gif": (b"GIF87a", b"GIF89a")}


def validate_image_url(url: str, strict: bool) -> str:
    """Parse without rewriting signed URLs or contacting their host."""
    invalid = HTTPException(422, "Invalid image HTTPS URL")
    if (not 1 <= len(url) <= 2048 or "\\" in url or "#" in url
            or any(c.isspace() or unicodedata.category(c).startswith("C") for c in url)):
        raise invalid
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username is not None:
            raise invalid
        if parsed.port == 0 or parsed.netloc.endswith(":"):
            raise invalid
        if parsed.netloc.startswith("["):
            if not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", parsed.netloc):
                raise invalid
            ipaddress.IPv6Address(host)
        else:
            ascii_host = host.removesuffix(".").encode("idna").decode("ascii")
            if (len(ascii_host) > 253 or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in ascii_host.split("."))):
                raise invalid
    except (UnicodeError, ValueError):
        raise invalid from None
    if strict and not parsed.path.lower().endswith(tuple("." + ext for ext in _FORMATS)):
        if not any((key in {"format", "fm"} and value.lower() in _FORMATS)
                   or (key == "response-content-type" and value.lower() in {
                       "image/jpeg", "image/webp", "image/png", "image/gif"})
                   for key, value in parse_qsl(parsed.query)):
            raise invalid
    return url


def validate_data_uri(uri: str) -> tuple[str, int]:
    """Validate canonical base64 in bounded blocks, retaining only the signature."""
    invalid = HTTPException(422, "Invalid embedded image")
    match = _DATA_PREFIX.match(uri)
    if not match:
        raise invalid
    start = match.end()
    length = len(uri) - start
    if length > 13_981_016:
        raise HTTPException(413, "Embedded images exceed 10 MiB")
    if not length or length % 4:
        raise invalid
    size = 0
    signature = b""
    step = 65536
    for offset in range(start, len(uri), step):
        block = uri[offset:offset + step]
        try:
            decoded = base64.b64decode(block, validate=True)
        except (binascii.Error, ValueError):
            raise invalid from None
        if "=" in block and (offset + step < len(uri) or base64.b64encode(decoded).decode("ascii") != block):
            raise invalid
        if offset == start:
            signature = decoded[:12]
        size += len(decoded)
    if size > MAX_INLINE:
        raise HTTPException(413, "Embedded images exceed 10 MiB")
    mime = match[1]
    if mime == "webp":
        if not (signature.startswith(b"RIFF") and signature[8:12] == b"WEBP"):
            raise invalid
    elif not signature.startswith(_SIGNATURES[mime]):
        raise invalid
    return uri, size


def media_caption(url: str) -> str:
    if url.startswith("data:"):
        return "Image"
    segment = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    return "".join(c for c in segment if c not in "/\\" and
                   not unicodedata.category(c).startswith("C"))[:200] or "Image"


def validate_layout(project: Domain | None, content_type: str | None, has_image: bool,
                    *, tags: bool = False, spans: bool = False) -> None:
    if project is None or not project.modality_enforced:
        return
    if (project.content_type, project.label_schema) not in VALID_COMBINATIONS:
        raise HTTPException(422, "Unsupported content type and label schema")
    if project.content_type == "image":
        if not has_image:
            raise HTTPException(422, "Image projects require item_media_url")
        if content_type != "image_classification" or spans or tags:
            raise HTTPException(422, "Content does not match project modality")
    else:
        expected = {"multi": "text_multilabel", "ner": "text_ner"}.get(project.label_schema)
        if (has_image or (tags and project.label_schema != "multi") or
                (spans and project.label_schema != "ner") or
                (content_type is not None and content_type != expected)):
            raise HTTPException(422, "Content does not match project modality")


def validate_media_for_project(project: Domain | None, content_type: str | None,
                               image_url: str | None, *, tags: bool = False, spans: bool = False) -> None:
    """Check an already syntax-validated new write against the locked project's policy."""
    validate_layout(project, content_type, bool(image_url), tags=tags, spans=spans)
    if image_url and image_url.startswith("data:"):
        if not inline_images_enabled():
            raise HTTPException(422, "Embedded images are not enabled")
    elif image_url and project is not None and project.modality_enforced:
        validate_image_url(image_url, strict=True)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def inline_images_enabled() -> bool:
    return _enabled("DLJ_INLINE_IMAGES_ENABLED")


def get_enabled_combinations() -> list[tuple[str, str]]:
    """Return release-enabled project pairs in stable UI order."""
    combinations = [("text", "single")]
    image = _enabled("DLJ_IMAGE_PROJECTS_ENABLED")
    multilabel = _enabled("DLJ_MULTILABEL_PROJECTS_ENABLED")
    ner = _enabled("DLJ_NER_PROJECTS_ENABLED")
    if image:
        combinations.append(("image", "single"))
    if multilabel:
        combinations.append(("text", "multi"))
        if image:
            combinations.append(("image", "multi"))
    if ner:
        combinations.append(("text", "ner"))
    return combinations


def validate_project_modality(content_type: object, label_schema: object) -> tuple[str, str]:
    """Validate axes against durable and release-time policy."""
    if not isinstance(content_type, str) or not isinstance(label_schema, str):
        raise HTTPException(422, "Invalid project modality")
    if content_type not in VALID_CONTENT_TYPES or label_schema not in VALID_LABEL_SCHEMAS:
        raise HTTPException(422, "Unsupported content type and label schema")
    pair = (content_type, label_schema)
    if pair not in VALID_COMBINATIONS:
        raise HTTPException(422, "Invalid project modality")
    if pair not in get_enabled_combinations():
        raise HTTPException(422, "Project modality is not enabled")
    return pair


async def check_modality_locked(domain: Domain, session: AsyncSession) -> bool:
    """A project policy becomes immutable as soon as any label row exists."""
    return bool(await session.scalar(select(exists().where(
        LabelLog.tenant_id == domain.tenant_id,
        LabelLog.domain_id == domain.domain_id,
    ))))
