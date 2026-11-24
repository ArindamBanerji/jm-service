"""Public legal and attribution pages."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Legal"])

TERMS_HTML = """<!doctype html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Terms of Service — RGI Data Label Judgment</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.7;color:#1f2937}
h1{font-size:1.8rem}h2{font-size:1.3rem;margin-top:2rem}a{color:#2563eb}</style></head><body>
<h1>Terms of Service</h1>
<p><strong>Effective:</strong> December 1, 2026</p>
<p><strong>Service provider:</strong> Dakshineshwari LLC</p>
<h2>1. Service Description</h2>
<p>RGI Data Label Judgment ("DLJ") is a verification intelligence layer for data labeling.
It scores, verifies, and improves label quality. It is not an annotation platform and does
not replace human review.</p>
<h2>2. Accounts and API Keys</h2>
<p>Each tenant uses an API key for authenticated scoring. You are responsible for key security.
Dakshineshwari LLC may revoke keys for abuse or violation of these terms.</p>
<h2>3. Payments</h2>
<p>Payments are processed by Paddle, which acts as the merchant of record.
Billing disputes, refund requests, and payment questions should be directed to the
Paddle customer portal. Dakshineshwari LLC provides the service;
Paddle handles the commercial transaction.</p>
<h2>4. Data Handling</h2>
<p><strong>Label Health Report (free):</strong> Data processed in memory, never stored,
discarded after response. No account required.</p>
<p><strong>Authenticated scoring:</strong> Label data, optional source text, factors, annotator IDs, and engine state stored
in managed PostgreSQL. Data belongs to you. Your data is not used for training or
any other purpose beyond providing the service.</p>
<p>Source text is optional and limited to 32 KiB UTF-8 per label. Do not submit identifiable
patient information unless you are authorized to provide it for this service.</p>
<h2>5. Service Level</h2>
<p>Free trial: best-effort availability, no SLA.<br>
Starter/Professional: 99% monthly uptime target.<br>
Business/Scale: 99.5% monthly uptime target.<br>
Enterprise: custom SLA in separate agreement.</p>
<h2>6. Limitation of Liability</h2>
<p>The service is provided as-is. Dakshineshwari LLC does not guarantee labeling accuracy.
The service provides recommendations; human review decisions remain your responsibility.
Liability is limited to fees paid in the prior 12 months.</p>
<h2>7. Termination</h2>
<p>You may cancel anytime via the Paddle customer portal. Data is retained for
30 days after cancellation, then deleted. You may request immediate deletion by email.</p>
<h2>8. Acceptable Use</h2>
<p>No abuse of anonymous endpoints. No reverse-engineering of the scoring engine.
Rate limiting is enforced.</p>
<h2>9. Governing Law</h2>
<p>These terms are governed by the laws of the State of New Jersey, United States.</p>
<h2>10. Contact</h2>
<p>Questions: <a href="mailto:arindam.banerji@gmail.com">arindam.banerji@gmail.com</a></p>
</body></html>"""

PRIVACY_HTML = """<!doctype html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Privacy Policy — RGI Data Label Judgment</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.7;color:#1f2937}
h1{font-size:1.8rem}h2{font-size:1.3rem;margin-top:2rem}a{color:#2563eb}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #d1d5db;padding:8px 12px;text-align:left}th{background:#f3f4f6}</style></head><body>
<h1>Privacy Policy</h1>
<p><strong>Effective:</strong> December 1, 2026</p>
<p><strong>Data controller:</strong> Dakshineshwari LLC</p>
<h2>1. Data We Collect</h2>
<p><strong>Anonymous reports:</strong> CSV data processed in memory, not stored, not logged.
IP address logged for rate limiting only.</p>
<p><strong>Authenticated usage:</strong> Label IDs, categories, optional source text, factor values,
annotator IDs, actions, verification outcomes, timestamps. Source text is retained with
the label and shown only through authenticated, tenant-scoped label detail requests.
Pending lists expose at most the first 80 Unicode characters as a preview.</p>
<p><strong>Account data:</strong> Tenant name, contact email when provided, API key hash (never plaintext), creation date,
tier, usage counters, and Paddle customer ID when linked.</p>
<p>No cookies on the API. The Review UI uses localStorage for domain selection and its API key.
Clearing the key in Settings removes that browser copy; it does not revoke the server key.</p>
<h2>2. How We Use Data</h2>
<p>Solely to provide the service. Not sold. Not used for training.
Not shared with third parties except infrastructure providers listed below.</p>
<h2>3. Data Retention</h2>
<p>Active accounts: data retained while subscription is active.<br>
Cancelled accounts: 30 days, then deleted.<br>
Anonymous reports: zero retention.</p>
<h2>4. Data Location</h2>
<p>United States (Railway hosting, US East region).</p>
<h2>5. Data Deletion</h2>
<p>Request deletion of all your data via email. Processed within 5 business days.</p>
<h2 id="sub-processors">6. Sub-processors</h2>
<table><thead><tr><th>Provider</th><th>Purpose</th></tr></thead><tbody>
<tr><td>Railway</td><td>Application hosting, PostgreSQL</td></tr>
<tr><td>Paddle</td><td>Payment processing (merchant of record)</td></tr>
<tr><td>Resend</td><td>Transactional email</td></tr>
</tbody></table>
<h2>7. GDPR</h2>
<p>Optional source text may contain sensitive data supplied by a customer. Customers
control what they submit and must have an appropriate basis for processing it.
Data Processing Addendum available on request for Enterprise tier.</p>
<h2>8. Contact</h2>
<p>Privacy questions: <a href="mailto:arindam.banerji@gmail.com">arindam.banerji@gmail.com</a></p>
</body></html>"""

ATTRIBUTION_HTML = """<!doctype html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Open-Source Attribution — RGI Data Label Judgment</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.7;color:#1f2937}
h1{font-size:1.8rem}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #d1d5db;padding:8px 12px;text-align:left}th{background:#f3f4f6}</style></head><body>
<h1>Open-Source Attribution</h1>
<p>RGI Data Label Judgment is built with the following open-source software:</p>
<table><thead><tr><th>Package</th><th>License</th><th>Author</th></tr></thead><tbody>
<tr><td>Graph Attention Engine</td><td>Apache 2.0</td><td>Dakshineshwari LLC</td></tr>
<tr><td>FastAPI</td><td>MIT</td><td>Sebastián Ramírez</td></tr>
<tr><td>SQLAlchemy</td><td>MIT</td><td>Mike Bayer</td></tr>
<tr><td>Pydantic</td><td>MIT</td><td>Samuel Colvin</td></tr>
<tr><td>Uvicorn</td><td>BSD-3</td><td>Encode</td></tr>
<tr><td>asyncpg</td><td>Apache 2.0</td><td>MagicStack</td></tr>
<tr><td>WeasyPrint</td><td>BSD-3</td><td>Kozea</td></tr>
<tr><td>ReportLab</td><td>BSD-3</td><td>ReportLab Inc.</td></tr>
<tr><td>SlowAPI</td><td>MIT</td><td>Laurent Savaete</td></tr>
<tr><td>React</td><td>MIT</td><td>Meta</td></tr>
<tr><td>Recharts</td><td>MIT</td><td>recharts team</td></tr>
<tr><td>Tailwind CSS</td><td>MIT</td><td>Tailwind Labs</td></tr>
</tbody></table>
</body></html>"""


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_of_service() -> str:
    return TERMS_HTML


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy() -> str:
    return PRIVACY_HTML


@router.get("/attribution", response_class=HTMLResponse, include_in_schema=False)
async def attribution() -> str:
    return ATTRIBUTION_HTML
