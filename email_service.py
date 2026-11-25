"""Transactional email through the Resend HTTP API."""
from __future__ import annotations

import os
from html import escape

import httpx

FROM_ADDRESS = "RGI Data Label Judgment <label@dakshineshwari.net>"


async def send_email(to: str, subject: str, html: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"from": FROM_ADDRESS, "to": [to], "subject": subject, "html": html},
                timeout=10.0,
            )
            return resp.status_code == 200
    except Exception:
        return False


def api_key_email(api_key: str) -> tuple[str, str]:
    subject = "Your RGI Data Label Judgment API Key"
    html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto">
    <h2>Welcome to RGI Data Label Judgment</h2>
    <p>Your API key:</p>
    <pre style="background:#f3f4f6;padding:16px;border-radius:8px;font-size:14px;word-break:break-all">{escape(api_key)}</pre>
    <p>This key is shown once. Store it securely.</p>
    <p><strong>Quickstart:</strong></p>
    <ol>
    <li>Upload a CSV at <a href="https://dlj.dakshineshwari.net">dlj.dakshineshwari.net</a></li>
    <li>POST /v1/domains/{{domain_id}}/score with your factors</li>
    <li>POST /v1/domains/{{domain_id}}/learn with the verified outcome</li>
    </ol>
    <p>API docs: <a href="https://dlj.dakshineshwari.net/docs">dlj.dakshineshwari.net/docs</a></p>
    <p>— Arindam Banerji, Dakshineshwari LLC</p></div>"""
    return subject, html


async def send_api_key_email(to: str, api_key: str) -> bool:
    subject, html = api_key_email(api_key)
    return await send_email(to, subject, html)


async def send_signup_challenge_email(to: str, token: str) -> bool:
    """Deliver proof of mailbox control without issuing an account credential."""
    html = ("<p>Enter this one-time code in the DLJ signup form within 30 minutes:</p>"
            f"<pre>{escape(token)}</pre>")
    return await send_email(to, "Confirm your DLJ email", html)


def trial_expiring_email() -> tuple[str, str]:
    subject = "Your DLJ trial expires in 2 days"
    html = """<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto">
    <h2>Your trial is ending soon</h2>
    <p>Your 14-day free trial of RGI Data Label Judgment expires in 2 days.</p>
    <p>Upgrade to keep scoring: <a href="https://dlj.dakshineshwari.net/#/settings">Manage subscription</a></p>
    <p>— Arindam Banerji, Dakshineshwari LLC</p></div>"""
    return subject, html


def trial_expired_email() -> tuple[str, str]:
    subject = "Your DLJ trial has ended"
    html = """<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto">
    <h2>Trial ended</h2>
    <p>Your 14-day free trial of RGI Data Label Judgment has ended.</p>
    <p>Your data is preserved for 30 days. Upgrade to resume scoring:</p>
    <p><a href="https://dlj.dakshineshwari.net/#/settings">Upgrade now</a></p>
    <p>— Arindam Banerji, Dakshineshwari LLC</p></div>"""
    return subject, html


def cancellation_email() -> tuple[str, str]:
    subject = "Your DLJ subscription has been cancelled"
    html = """<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto">
    <h2>Subscription cancelled</h2>
    <p>Your RGI Data Label Judgment subscription has been cancelled.</p>
    <p>Your data will be retained for 30 days and then deleted.</p>
    <p>Changed your mind? <a href="https://dlj.dakshineshwari.net/#/settings">Reactivate</a></p>
    <p>— Arindam Banerji, Dakshineshwari LLC</p></div>"""
    return subject, html
