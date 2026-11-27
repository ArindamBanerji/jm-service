import { useEffect, useState } from 'react'

const sections = [
  ['getting-started', 'Getting Started'], ['uploading-data', 'Uploading Data'],
  ['scoring-verification', 'Scoring & Verification'], ['predictions', 'Predictions'],
  ['export', 'Export'], ['webhooks', 'Webhooks'], ['python-client', 'Python Client'],
  ['billing', 'Billing'],
] as const

function goTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  history.replaceState(history.state, '', `#/docs?section=${encodeURIComponent(id)}`)
}

export default function GuidePage() {
  const [mobileSection, setMobileSection] = useState<string>(sections[0][0])
  useEffect(() => {
    const section = new URLSearchParams(window.location.hash.split('?')[1]).get('section')
    const match = sections.find(([id]) => id === section)
    if (match) { setMobileSection(match[0]); document.getElementById(match[0])?.scrollIntoView() }
  }, [])
  return <div className="page guide-page"><div className="eyebrow">DLJ Guide</div><h1>Build a reliable review loop</h1>
    <p className="subtitle">From the first API key to durable exports and signed delivery, this guide follows the production workflow.</p>
    <label className="field guide-mobile-nav">Guide section<select value={mobileSection} onChange={event => {
      setMobileSection(event.target.value as typeof mobileSection); goTo(event.target.value)
    }}>{sections.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
    <div className="guide-layout"><aside className="card guide-nav" aria-label="Guide sections">
      {sections.map(([id, label]) => <button key={id} onClick={() => goTo(id)}>{label}</button>)}
    </aside><article className="card card-pad guide-content">
      <section id="getting-started"><h2>Getting Started</h2><p><a href="#/quickstart">Start the interactive quickstart</a> or create an account from <a href="#/signup">Sign Up</a>, confirm the mailbox challenge, and save the API key shown once. Add the key in the sidebar, open Projects, and create a project with its categories, factors, and actions.</p></section>
      <section id="uploading-data"><h2>Uploading Data</h2><p>Send JSON batches of 1–100 labels to <code>POST /v1/projects/&lbrace;project_id&rbrace;/labels/batch</code>. Each chunk carries a stable replay key. Retry the same body with the same key after 429 or server errors so committed work is never duplicated.</p>
        <p>For an image project, supply <code>item_media_url</code> such as <code>https://images.example/bird.png</code> and an optional caption in <code>item_text</code>. When embedded images are enabled, a base64 data URI such as <code>data:image/png;base64,…</code> stores the image with the project. Each request allows 10 MiB of decoded images and 20 MiB of JSON.</p>
        <p>External images load after consent and disclose the reviewer’s IP address to the image host. An expired link shows “Image not available.” Embedded images count toward storage and remain with the revision until retention cleanup. Authorized CSV and JSONL exports can contain the complete image or signed URL.</p></section>
      <section id="scoring-verification"><h2>Scoring &amp; Verification</h2><p>DLJ scores each label from project factors and returns a recommendation, confidence, autonomy tier, and conservation state. A reviewer confirms the observed action and outcome. In Python, pass the observation explicitly, e.g. <code>client.verify(project_id, label_id, "approve", &#123;"verified_outcome": False&#125;)</code>. Category or content changes create a revision, preserve lineage, and keep the previous evidence active until re-adjudication.</p></section>
      <section id="predictions"><h2>Predictions</h2><p>Import predictions with model source, version, confidence, category, content, and factors. Automation remains off by default and only passes when the model floor, DLJ approval, autonomous tier, conservation gate, and named-annotator gate all pass. Machine approval never trains the engine. Use the Predictions tab for explicit human review or reopen.</p></section>
      <section id="export"><h2>Export</h2><p>Reviewers can export the current logical revision as JSONL, escaped CSV, or spaCy DocBin. Filters cover review state, category, annotator, and UTC dates. Exports include provenance, source text, factors, structured content, human outcome, model confidence, and DLJ confidence.</p></section>
      <section id="webhooks"><h2>Webhooks</h2><p>Project admins register public HTTPS endpoints for <code>label.verified</code>, <code>prediction.auto_approved</code>, and <code>webhook.test</code>. Read <code>ts</code> and <code>h1</code> from <code>Paddle-Signature</code>. Compare h1 in constant time with the hex HMAC-SHA256 of the timestamp, a period, and the exact received body, using your signing secret. Deduplicate on event_id. DLJ retries transient failures with bounded backoff and never follows redirects.</p></section>
      <section id="python-client"><h2>Python Client</h2><p>The single-file client uses only <code>requests</code>, preserves replay keys across retries, chunks uploads, and streams downloads.</p><a className="button" href="/dlj_client.py" download>Download dlj_client.py</a></section>
      <section id="billing"><h2>Billing</h2><p>Trials use the published daily allowance. Paid tiers increase capacity and may enable automation when project gates pass. Upgrade from account Settings. Paused or past-due accounts become restricted, and cancellation falls back to trial-rate capacity while retention policy runs.</p></section>
    </article></div>
  </div>
}
