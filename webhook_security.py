"""Outbound webhook encryption, egress validation and exact-byte signing."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import os
import socket
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException


class DestinationResolutionError(HTTPException):
    """The destination could not be resolved in this attempt."""


def _fernet() -> Fernet:
    encoded = os.getenv("WEBHOOK_ENCRYPTION_KEY", "")
    try:
        raw = base64.urlsafe_b64decode(encoded.encode())
        if len(raw) != 32:
            raise ValueError
        return Fernet(encoded.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "Webhook encryption key is not configured") from exc


def encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise RuntimeError("Webhook secret cannot be decrypted") from exc


def signature(secret: str, timestamp: str, canonical_body: str) -> str:
    payload = timestamp.encode() + b"." + canonical_body.encode("utf-8")
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global and not any((
        address.is_private, address.is_loopback, address.is_link_local,
        address.is_multicast, address.is_reserved, address.is_unspecified,
    ))


async def validate_public_https(url: str) -> str:
    """Validate syntax and every resolved address immediately before use."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise HTTPException(422, 'Invalid webhook URL') from None
    if any(ord(char) < 33 or char == chr(92) for char in url):
        raise HTTPException(422, 'Invalid webhook URL')
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise HTTPException(422, "Webhook URL must be a public HTTPS URL")
    if len(url) > 2048:
        raise HTTPException(422, "Webhook URL exceeds 2048 characters")
    try:
        port = parsed.port or 443
    except ValueError:
        raise HTTPException(422, "Webhook URL has an invalid port") from None
    try:
        async with asyncio.timeout(10):
            records = await asyncio.to_thread(
                socket.getaddrinfo, parsed.hostname, port, 0, socket.SOCK_STREAM)
    except OSError:
        raise DestinationResolutionError(422, "Webhook hostname could not be resolved") from None
    except UnicodeError:
        raise HTTPException(422, "Invalid webhook hostname") from None
    addresses = {record[4][0].split("%", 1)[0] for record in records}
    if not addresses or any(not _public_address(address) for address in addresses):
        raise HTTPException(422, "Webhook URL must resolve only to public addresses")
    return sorted(addresses)[0]
