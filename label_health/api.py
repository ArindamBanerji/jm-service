"""Anonymous Label Health Report routes."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import csv
from typing import Any
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.datastructures import UploadFile
from label_health.ingest import infer_config, normalize_csv, validate_csv
from label_health.analyze import run_analysis
from label_health.render import render_html_report, render_pdf

router = APIRouter(prefix="/v1/label-health", tags=["Label Health Report"])
_MAX_BYTES = 10 * 1024 * 1024
_executor = ThreadPoolExecutor(max_workers=2)
_slots = asyncio.Semaphore(2)
_TIMEOUT = 60


def _run_sync(data: bytes, output: str) -> Any:
    if not data or b"\x00" in data:
        raise ValueError("CSV is empty or contains invalid bytes")
    try:
        source = data.decode("utf-8-sig")
        header = next(csv.reader(source.splitlines(), strict=True))
        if len(set(header)) != len(header) or any(not name.strip() for name in header):
            raise ValueError("CSV headers must be unique and nonempty")
        df = normalize_csv(pd.read_csv(BytesIO(data), encoding="utf-8-sig", on_bad_lines="error"))
    except (UnicodeError, csv.Error, StopIteration, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ValueError(f"Invalid CSV: {exc}") from exc
    checked = validate_csv(df)
    if not checked.is_valid:
        raise ValueError(checked.errors)
    config = infer_config(df)
    report = run_analysis(df, config)
    report["warnings"].extend(checked.warnings)
    if output == "json":
        return report
    html = render_html_report(report)
    return render_pdf(html) if output == "pdf" else html


async def _analyze(file: UploadFile, output: str, *, slot_acquired: bool = False) -> Any:
    if not slot_acquired:
        if _slots.locked():
            raise HTTPException(status_code=503, detail="Report workers are busy")
        await _slots.acquire()
    try:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=422, detail=["Upload a CSV file"])
        data = await file.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise HTTPException(status_code=413, detail="CSV exceeds 10 MiB")
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_executor, _run_sync, data, output)
    except BaseException:
        _slots.release()
        raise
    future.add_done_callback(lambda _: _slots.release())
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=_TIMEOUT)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Report generation timed out") from exc
    except ValueError as exc:
        detail = exc.args[0] if isinstance(exc.args[0], list) else [str(exc)]
        raise HTTPException(status_code=422, detail=detail) from exc


async def _analyze_request(request: Request, output: str) -> Any:
    """Reserve a worker slot before Starlette parses the multipart body."""
    if _slots.locked():
        raise HTTPException(status_code=503, detail="Report workers are busy")
    await _slots.acquire()
    try:
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=422, detail=["Upload a CSV file"])
    except BaseException:
        _slots.release()
        raise
    try:
        return await _analyze(file, output, slot_acquired=True)
    finally:
        await form.close()


@router.post("/analyze")
async def analyze(request: Request) -> JSONResponse:
    return JSONResponse(await _analyze_request(request, "json"))


@router.post("/report")
async def report_html(request: Request) -> HTMLResponse:
    return HTMLResponse(await _analyze_request(request, "html"))


@router.post("/report/pdf")
async def report_pdf(request: Request) -> Response:
    return Response(await _analyze_request(request, "pdf"), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="label_health_report.pdf"'})
