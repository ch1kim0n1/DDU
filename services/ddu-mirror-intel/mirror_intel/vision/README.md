# Photo Intelligence & ID Verification

Mirror’s **Engineer C** surface: turn an operator-chosen photo (or photo ID) into
schema-valid findings, without running heavy ML on the critical demo path.

Product line: *Start with yourself. See what they'd see.*

---

## What this system does

| Capability | What the user sees | How it is produced |
|---|---|---|
| **Photo intelligence** | EXIF GPS/device, objects (plate, badge, …), location guesses, face-blur advice | Live EXIF + **precomputed cache** by image sha256 |
| **Liveness** | Blink / head-turn challenge | MediaPipe FaceMesh **in the browser**; server only stores challenge + optional one frame |
| **Closed-corpus face link** | “Same face as verified avatar” | Session-scoped corpus only — **no open-web face search** |
| **Photo ID (demo)** | Student ID / driver’s license → session labeled **ID verified** | **Mock OCR** from image hash; redacted `object_exposure` findings |

Findings enter the same session graph everyone else consumes (scoring, map/3D, evidence drawer).

---

## How it is made

### Layout

```
mirror_intel/vision/
  pipeline.py      Photo analyze — EXIF + cache → findings
  exif.py          Live GPS / device / timestamp from bytes
  cache.py         sha256 → objects / geo / face_boxes
  builders.py      Finding construction + reveal tokens
  face.py          Redaction preview (+ optional CompreFace)
  corpus.py        Closed-corpus enroll / match
  liveness.py      Challenge / TTL / skip store
  id_verify.py     Demo student ID / DL mock OCR + assurance
  routes.py        HTTP under /intel/vision/*

data/vision_cache/
  index.json       Hash → cached detections
  demo_*.jpg       Curated demo photos
```

UI:

| File | Role |
|---|---|
| `ui/ddu-ui/src/VisionPanel.tsx` | In-app photo demos / upload / payoff cue |
| `ui/ddu-ui/src/LivenessChallenge.tsx` | Browser FaceMesh challenge |
| `ui/ddu-ui/src/IdDocumentVerify.tsx` | Student ID / driver’s license upload |
| `ui/ddu-ui/src/IdentityGate.tsx` | Step 2 — Live face **or** Photo ID |
| `ui/ddu-ui/src/mirror-api.ts` | Client helpers |

### Photo intelligence pipeline

1. Operator uploads bytes (or clicks a curated demo).
2. `analyze_upload()` hashes the file (`sha256`).
3. **EXIF is always read live** → `gps_exposure` / `device_fingerprint` when present (coords vaulted behind reveal tokens).
4. Cache lookup → on hit, attach `object_exposure` + `location_inference` (`hypothesis` only). Method/disclosures say Grounded-SAM-2 / GeoCLIP were **not** run live.
5. Redaction preview from cached face boxes (or optional CompreFace / empty stub).
6. `session.add_findings(...)` with `subject_ref` forced to the session seed.

Heavy models stay off the stage path on purpose. Live `ddu-vision` / `ddu-geo` exist in the full DDU stack; Mirror does not call them for this demo flow.

### Liveness

1. `POST /liveness/start` → server issues `challenge_id` + `blink` | `turn_left` | `turn_right`.
2. Browser runs FaceMesh; progress ring fills when the gesture is held.
3. `POST /liveness/complete` with that `challenge_id` + optional JPEG frame.
4. Skip clears challenge + face corpus; later face match returns `409`.

### Photo ID (demo path)

1. Operator picks **Student ID** or **Driver’s license** and uploads an image.
2. Server runs **mock OCR** (deterministic fields from content hash) — disclosed as `mock:id-ocr-demo`.
3. One `object_exposure` finding is ingested; PII rows are `REDACTED` until reveal.
4. Session assurance becomes `id_document` (UI badge: **ID verified**).
5. Wipe / session delete clears ID state with liveness + corpus.

This is **not** government KYC and does **not** match a face to the ID portrait.

### Design rules

1. No free-text “target someone else” — photos are operator uploads.
2. No third-party traversal — `subject_ref` = session seed; incidental faces are redaction-only.
3. Closed corpus only for face matching.
4. Redact at the boundary (GPS, matched labels, ID fields).
5. Ephemeral — liveness frame TTL; wipe calls `cleanup_session_vision`.
6. Skip must work — no dangling biometric state.

---

## How it is used

### Run locally

```powershell
# Terminal 1 — API (:8120)
cd <repo>
.\.venv\Scripts\python.exe -m pip install -e libs\ddu-py-common -e services\ddu-mirror-intel
.\.venv\Scripts\python.exe services\ddu-mirror-intel\app.py

# Terminal 2 — UI
cd ui\ddu-ui
npm install
npm run dev
```

Open http://localhost:5173.

### Onboarding (Step 2)

1. Landing → **Begin** → identity wizard (email / handle).
2. Session is created → **Step 2: Live check**
   - **Live face** — consent → start → complete blink/turn (or Confirm manually if FaceMesh fails).
   - **Photo ID** — choose student ID or DL → consent → upload → Verify.
   - Or **Skip** → email-only assurance.
3. **Step 3** — scope what to scan (badge shows Live face / ID verified / Email-only).
4. **Step 4** — main Mirror workspace.

**Mock preview** on the landing page skips Step 2 and jumps into the app.

### In-app photo intelligence

Right rail → **Vision / Photo intelligence**:

1. Click a curated demo (e.g. vacation driveway) or upload your own.
2. Panel shows cache timing, disclosures, redaction preview.
3. Findings land in the graph; GPS/location findings cue the **Map** view.

Demo assets (must match `index.json` hashes exactly):

| Slug | Story |
|---|---|
| `vacation_plate` | Residential GPS + plate + house number |
| `badge_selfie` | Workplace GPS + badge + faces |
| `stripped_street` | No EXIF — geo + street-sign objects still fire |
| `home_backyard` | Home GPS + mailbox |

### HTTP API (`/intel/vision/...`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/demos` | List curated demo metadata |
| `GET` | `/demos/{slug}` | Download demo JPEG |
| `POST` | `/analyze` | Multipart photo → EXIF + cache → ingest |
| `POST` | `/redaction-preview` | Face boxes / blur advice |
| `POST` | `/face/enroll` | Closed-corpus enroll |
| `POST` | `/face/match` | Match → `face_link` findings |
| `POST` | `/liveness/start` | Issue challenge |
| `POST` | `/liveness/complete` | Client pass/fail + optional frame |
| `POST` | `/liveness/skip` | Skip face; clear corpus |
| `GET` | `/liveness/{session_id}` | Liveness status |
| `POST` | `/id-verify` | Student ID / DL demo verify |
| `GET` | `/id-verify/{session_id}` | ID verify status |

#### Analyze

Form fields: `session_id`, `file`, optional `platform`, `parent_id`, `hop_depth`.

#### ID verify

Form fields: `session_id`, `document_kind` (`student_id` | `drivers_license`), `file`.

```powershell
# After creating a session
curl -s http://localhost:8120/intel/vision/analyze `
  -F "session_id=s_c" -F "platform=instagram" `
  -F "file=@services/ddu-mirror-intel/mirror_intel/data/vision_cache/demo_vacation_plate.jpg"

curl -s http://localhost:8120/intel/vision/id-verify `
  -F "session_id=s_c" -F "document_kind=drivers_license" `
  -F "file=@path\to\id.jpg"
```

### Finding types (photo / ID path)

| Type | Source | Typical state |
|---|---|---|
| `gps_exposure` | Live EXIF GPS | `confirmed` |
| `device_fingerprint` | Live EXIF make/model | `confirmed` |
| `object_exposure` | Cache SAM-2 **or** mock ID OCR | `likely` |
| `location_inference` | Cache GeoCLIP | **`hypothesis` only** |
| `face_link` | Closed-corpus match | `likely` |

### Optional env

| Variable | Effect |
|---|---|
| `COMPREFACE_URL` / `COMPREFACE_API_KEY` | Live face detect for redaction preview |

Not required for the offline demo.

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest services\ddu-mirror-intel\test_vision_engineer_c.py -q
```

Covers demo cache DoD (&lt;2s), EXIF, geo hypothesis without GPS, closed corpus, liveness pass/fail/skip, wipe cleanup, and ID-verify demo path.

---

## What we deliberately do not ship here

- Live Grounded-SAM-2 / GeoCLIP on every arbitrary upload (cache-first demo path).
- Open-web face search.
- Treating GeoCLIP as a confirmed address.
- Real government ID OCR / KYC, or face-to-ID portrait match (stricter path not enabled).

For the longer Engineer C charter, see [`docs/engineer-c-vision-biometrics.md`](../../../../docs/engineer-c-vision-biometrics.md).
