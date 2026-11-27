# DLJ Multi-Modality Design — Closing the Competitive Gap
**Date:** November 26, 2026 · **Version:** v2 (Astra-reviewed, 4 P1s fixed)
**Status:** Design complete — IMG-1 Codex prompt ready
**Authority:** Competitive analysis (Snorkel, Labelbox, Encord gap), engine architecture (jm_core.py), Astra review
**Repo:** jm-service

---

## 1. Problem

DLJ is positioned as a "full-cycle data labeling platform" but only supports text classification. Every competitor supports image classification at minimum. This is the #1 buyer objection.

The scoring engine is modality-agnostic (confirmed by Astra review) — it operates on decision vectors, not content. The gap is exclusively in the upload pipeline and the annotation UI.

## 2. Architecture Principle

**The scoring engine MUST NOT change.** jm_core.py hash is frozen.

The engine computes on `{item_id, category, annotator, timestamp, factors}`. Content type is irrelevant to scoring. All modality support is in the UI layer and the upload/storage layer.

## 3. Schema Design (Astra P1 #4 fix: separate content_type from label_schema)

Two independent dimensions:

| Dimension | Column | Values | Examples |
|---|---|---|---|
| **Content type** | `content_type` on `domains` | `text`, `image` | What the annotator looks at |
| **Label schema** | `label_schema` on `domains` | `single`, `multi`, `ner` | How the annotator assigns labels |

This allows combinations: image + single-label, image + multi-label, text + NER, etc.

**Astra P1 #3 fix:** No `item_type` column on `label_log`. Content type is derived from the project.

### Migration (Phase 1 — image + single-label only)

```sql
-- Migration: add_modality_support.sql (repeat-safe, rollback-safe)

-- Content type and label schema on projects
ALTER TABLE domains ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) DEFAULT 'text';
ALTER TABLE domains ADD COLUMN IF NOT EXISTS label_schema VARCHAR(20) DEFAULT 'single';

-- Media URL on labels (for image items)
ALTER TABLE label_log ADD COLUMN IF NOT EXISTS item_media_url TEXT;

-- Item metadata (for future NER spans, multi-label sets)
ALTER TABLE label_log ADD COLUMN IF NOT EXISTS item_metadata JSONB;
```

**Backward compatibility:** All existing projects have `content_type='text'`, `label_schema='single'`. All existing labels have `item_media_url=NULL`, `item_metadata=NULL`. Zero behavior change.

## 4. Image Storage Contract (Astra P1 #1 + #2 fix)

**Phase 1: external URLs only.**

- Upload accepts `item_media_url` as an HTTPS URL
- **Format-only validation** on upload: must be a syntactically valid HTTPS URL ending in a known image extension (.jpg, .jpeg, .png, .webp, .gif) or containing a known image content-type parameter. No HTTP HEAD, no reachability check.
- DLJ does NOT host images. The URL must remain accessible for the item to render.
- **UI broken-image fallback:** if the image fails to load, show a placeholder with the URL and "Image not available" text. The label is still scoreable (category assignment works regardless).
- **Data URI support:** accept `data:image/{format};base64,...` with a 10MB size limit. Stored directly in `item_media_url`. Warn in docs that this bloats DB.
- `item_text` is optional for image items — used as alt text / search fallback. If not provided, store the filename from the URL.

**NOT in Phase 1:** Image hosting, thumbnail generation, CDN proxying, broken-link detection. These are Phase 2 if needed.

**Image size limits (Astra P2 #5):** Data URIs capped at 10MB. External URLs not size-checked (browser handles rendering). Docs note: "For best performance, images under 2MB and 2048×2048 recommended."

**CORS (Astra P2 #6):** `<img>` tags render cross-origin images without CORS. Known limitation for future bounding box (canvas requires CORS). Not a blocker for classification.

## 5. Phase 1 — Image Classification (IMG-1, 1-2 days)

### Backend changes

**Project creation:**
- POST /v1/projects accepts `content_type: "text" | "image"` (default "text")
- `label_schema` stays "single" for Phase 1
- Immutable after first label (prevents schema confusion)

**Upload:**
- POST /v1/projects/{id}/labels/batch:
  - For `content_type='image'` projects: `items[].item_media_url` required
  - `items[].item_text` optional (alt text)
  - Validate URL format only — no reachability check
  - Reject if project content_type doesn't match (no images in text projects)
- Data URI accepted with 10MB cap

**All other endpoints unchanged.** Scoring, smart sampling, SLA, conservation, export, webhooks — all operate on decision records, not content. They already return `item_text`; they now also return `item_media_url` when present.

**Export:** JSONL/CSV include `item_media_url` column. `content_type` in export header.

### Frontend changes

**Labeling queue:**
- If project `content_type='image'`: render `<img>` with `item_media_url`
  - `max-height: 400px`, `object-fit: contain`, centered above category buttons
  - `onerror` handler: show placeholder "Image not available" with URL text
- If `content_type='text'`: unchanged (render `item_text`)
- Category assignment, keyboard shortcuts, smart queue toggle — all unchanged

**Dashboard:** No change. Stats are category-based, not content-based.

**Project creation modal:** Add a "Content type" selector: Text (default) / Image. Help text: "Choose what your annotators will label. Can't be changed after the first label."

### What does NOT change
- jm_core.py (frozen hash)
- Conservation law, θ_min, centroid geometry
- Smart sampling (centroid distance)
- SLA badge, factor computation
- Webhooks (add media_url to payload when present)
- Python client (add optional media_url param)
- Quickstart (stays text — simplest onboarding)

### Tests

Backend (+8 PG):
1. test_create_image_project — content_type='image' persists
2. test_upload_image_items — media_url stored, item_text as alt text
3. test_upload_bad_url_format — rejects non-HTTPS, non-image URLs
4. test_upload_data_uri — base64 image accepted under 10MB
5. test_upload_data_uri_too_large — >10MB rejected
6. test_score_image_item — engine scores identically to text
7. test_smart_sampling_image — centroid distance works on image items
8. test_export_includes_media_url — JSONL has the field

Playwright (+4 PW):
1. test_image_project_creation — create project with content_type=image
2. test_image_in_queue — image renders in labeling queue
3. test_image_broken_fallback — bad URL shows placeholder (not crash)
4. test_image_label_and_score — assign category, see score breakdown

## 6. Phase 2 — Multi-Label Classification (Sprint 2, 2 days)

Separate from image support. `label_schema='multi'` on any `content_type`.

- Labeling UI: checkbox multi-select instead of radio/single-select
- Each category assignment scored independently (N decisions per item)
- Centroids: per-category, same as single-label
- Export: categories as JSON array
- Tests: +6 PG, +3 PW

## 7. Phase 3 — NER / Span Labeling (2-3 weeks — Astra P2 #7 corrected)

`label_schema='ner'` on `content_type='text'`.

- Span selection UI (click-drag, entity type dropdown)
- Partial overlap scoring (IoU on character positions, threshold TBD)
- May need modified agreement computation — deferred to Phase 3 design
- Tests: +15 PG, +8 PW (estimated)

**Not building:** Bounding box, video, audio, document layout. Customer-triggered.

## 8. Execution Plan

### IMG-1 Codex prompt (ready now)

Spark+high. Schema migration + backend + frontend + 8 PG + 4 PW.
Runs parallel with Notes+Guidelines (different files confirmed by Astra).
Ships before Prompt 12.

### Revised pipeline

```
Analytics UI (⏳ SENT)
  ↓
Notes+Guidelines  ←→  IMG-1 (parallel — different files, Astra confirmed)
  ↓                      ↓
Prompt 12 (covers everything including image support)
```

### Post-launch sprints (updated)

```
Sprint 1: Drift Alerts + Centroid Transfer + ML-1 (multi-label)
Sprint 2: NER-1 + NER-R (2-3 weeks) + SSO
```

### Positioning after each phase

| After | Qualifier |
|---|---|
| IMG-1 ships | "text and image classification" |
| ML-1 ships | "classification tasks" (drop modality qualifier) |
| NER ships | "Full-cycle data labeling platform" — no qualifier |

---

*DLJ Multi-Modality Design v2 · November 26, 2026 · Astra-reviewed*
*Engine confirmed modality-agnostic. 4 P1s fixed.*
*Phase 1 (image): 1-2 days, external URLs only, zero engine changes*
*Schema: content_type × label_schema (not a single enum)*
*IMG-1 runs parallel with Notes+Guidelines, before Prompt 12*
