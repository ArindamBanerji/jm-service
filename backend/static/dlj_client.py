"""Small, dependency-light client for the DLJ HTTP API.

Install ``requests`` and keep this file beside your application.  Every
retry reuses the same idempotency key, so a lost response cannot duplicate a
committed chunk.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path
import time
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

import requests

MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _upload_chunks(items: Iterable[dict[str, Any]], limit: int) -> Iterator[list[dict[str, Any]]]:
    # requests serializes the json= body with the standard spaced separators.
    key_length = len("client-upload-") + 36
    envelope = len(json.dumps({"request_key": "x" * key_length, "items": []}))
    chunk: list[dict[str, Any]] = []
    body_bytes = envelope
    decoded_bytes = 0
    for item in items:
        item_bytes = len(json.dumps(item, ensure_ascii=True, allow_nan=False))
        content = item.get("content")
        image = item.get("item_media_url") or (content.get("image_url") if isinstance(content, dict) else None)
        image_bytes = 0
        if isinstance(image, str) and image.startswith("data:"):
            start = image.find(",") + 1
            image_bytes = (len(image) - start) // 4 * 3 - int(image.endswith("=")) - int(image.endswith("=="))
        if item_bytes + envelope > MAX_JSON_BYTES or image_bytes > MAX_IMAGE_BYTES:
            raise ValueError("One item exceeds the upload byte limit")
        if chunk and (body_bytes + 2 + item_bytes > MAX_JSON_BYTES
                      or decoded_bytes + image_bytes > MAX_IMAGE_BYTES):
            yield chunk
            chunk = []
            body_bytes = envelope
            decoded_bytes = 0
        body_bytes += item_bytes + (2 if chunk else 0)
        decoded_bytes += image_bytes
        chunk.append(item)
        if len(chunk) == limit:
            yield chunk
            chunk = []
            body_bytes = envelope
            decoded_bytes = 0
    if chunk:
        yield chunk

class UploadError(RuntimeError):
    """A chunk failed. Replay its exact body with request_key to resolve an uncertain commit."""

    def __init__(self, committed: int, request_key: str, items: list[dict[str, Any]]) -> None:
        super().__init__(f"Upload stopped after {committed} confirmed items")
        self.committed = committed
        self.request_key = request_key
        self.items = items


class DLJClient:
    """Synchronous client for projects, labels, predictions and webhooks."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        # Only replay a write if the API can identify the original operation.
        body = kwargs.get('json') or {}
        attempts = 3 if method == 'GET' or body.get('request_key') else 1
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method, self.base_url + path, timeout=self.timeout, allow_redirects=False, **kwargs
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == attempts:
                    raise
            else:
                if 300 <= response.status_code < 400:
                    response.close()
                    raise requests.HTTPError("Unexpected redirect", response=response)
                if response.status_code != 429 and not 500 <= response.status_code < 600:
                    response.raise_for_status()
                    return response
                response.close()
                if attempt + 1 == attempts:
                    response.raise_for_status()
            time.sleep(0.5 * (2**attempt))
        raise RuntimeError("Retry budget exhausted")

    def create_project(
        self,
        name: str,
        categories: list[str],
        factors: list[str],
        actions: list[str],
        *,
        content_type: str | None = None,
        label_schema: str | None = None,
    ) -> dict[str, Any]:
        public_id = "-".join(name.lower().split())[:80] or f"project-{uuid.uuid4().hex[:8]}"
        return self._request("POST", "/v1/projects", json={
            "name": name,
            "public_domain_id": public_id,
            "categories": categories,
            "factors": factors,
            "actions": actions,
            **{k: v for k, v in (("content_type", content_type), ("label_schema", label_schema)) if v is not None},
        }).json()

    def upload(
        self, project_id: str, items: Iterable[dict[str, Any]], chunk_size: int = 100
    ) -> dict[str, Any]:
        if not 1 <= chunk_size <= 100:
            raise ValueError("chunk_size must be between 1 and 100")
        committed = 0
        chunks: list[dict[str, Any]] = []
        for chunk in _upload_chunks(items, chunk_size):
            request_key = f"client-upload-{uuid.uuid4()}"
            try:
                result = self._request(
                    "POST", f"/v1/projects/{project_id}/labels/batch",
                    json={"request_key": request_key, "items": chunk},
                ).json()
            except requests.RequestException as exc:
                raise UploadError(committed, request_key, chunk) from exc
            count = int(result.get("batch_size", len(result.get("results", []))))
            committed += count
            chunks.append({"request_key": request_key, "committed": count})
        return {"requested": committed, "committed": committed, "chunks": chunks}

    def verify(
        self,
        project_id: str,
        item_id: str,
        action: str,
        factors: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = factors or {}
        outcome = metadata.get("verified_outcome")
        if not isinstance(outcome, bool):
            raise ValueError("Supply an observed boolean in factors['verified_outcome']")
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/labels/verify",
            json={"label_id": item_id, "actual_action": action, "verified_outcome": outcome},
        ).json()

    def import_predictions(
        self, project_id: str, predictions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/predictions",
            json={"request_key": f"client-prediction-{uuid.uuid4()}", "items": predictions},
        ).json()

    def export(
        self, project_id: str, format: str = "jsonl", filters: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any] | bytes]:
        query = {**(filters or {}), "format": format}
        response = self._request(
            "GET", f"/v1/projects/{project_id}/export", params=query, stream=True
        )
        with response:
            if format == "jsonl":
                for line in response.iter_lines(chunk_size=64 * 1024):
                    if line:
                        yield json.loads(line)
            elif format == "csv":
                # The CSV parser's process-wide default (128 KiB) rejects valid embedded images.
                if csv.field_size_limit() < 32 * 1024 * 1024:
                    csv.field_size_limit(32 * 1024 * 1024)
                response.raw.decode_content = True
                # urllib3 otherwise marks the raw stream closed on its last nonempty
                # read; TextIOWrapper still needs one more read to detect EOF.
                response.raw.auto_close = False
                with io.TextIOWrapper(response.raw, encoding="utf-8", newline="") as source:
                    yield from csv.DictReader(source)
            else:
                yield from response.iter_content(64 * 1024)

    def save_export(self, project_id: str, destination: str, format: str = "jsonl",
                    filters: dict[str, Any] | None = None) -> None:
        """Publish the destination only after the complete response has arrived."""
        path = Path(destination)
        temporary = None
        try:
            with self._request("GET", f"/v1/projects/{project_id}/export",
                               params={**(filters or {}), "format": format}, stream=True) as response:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    for chunk in response.iter_content(64 * 1024):
                        output.write(chunk)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get_status(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/projects/{project_id}").json()

    def list_webhooks(self, project_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/v1/projects/{project_id}/webhooks").json()
        if not isinstance(result, list):
            raise TypeError("Webhook response was not a list")
        return result


if __name__ == "__main__":
    client = DLJClient("https://your-dlj-service.example", "dlj_your_api_key")
    project = client.create_project(
        "Medical review", ["MEDICATION", "CONDITION"], ["confidence", "difficulty"],
        ["approve", "reject"],
    )
    print("Created project", project["id"])
