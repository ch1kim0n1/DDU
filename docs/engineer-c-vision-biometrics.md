# Engineer C — Vision & Biometrics

**Owner charter:** produce the most visceral findings in the Mirror demo.  
**Product line:** *Start with yourself. See what they'd see.*  
**Spec:** [`DDU-Mirror-Project-Spec.md`](../DDU-Mirror-Project-Spec.md) §6.2, §6.5, §7 (Engineer C)  
**Findings contract:** [`services/ddu-mirror-intel/CONTRACT.md`](../services/ddu-mirror-intel/CONTRACT.md) (locked — do not invent new finding types)

---

## What this slice does

Engineer C turns an operator-chosen photo into schema-valid Mirror findings, then lands them in the same graph that Engineer B scores and Engineer D renders.

| Capability | What the user sees | Epistemic honesty |
|---|---|---|
| **EXIF extraction** | GPS + device metadata findings | Live parse of the uploaded bytes; coordinates stay vaulted behind reveal tokens |
| **Object exposure** | License plate, badge, house number, street sign, mailbox, … | Grounded-SAM-2 results are **pre-computed** and cached by file hash — disclosed in `method` |
| **Location inference** | Ranked neighbourhood hypotheses | GeoCLIP **pre-computed**; always `verification_state=hypothesis`, never confirmed |
| **Redaction preview** | “N faces detected — blur before posting” | Cache boxes for demo photos; optional CompreFace detect if configured |
| **Closed-corpus face link** | “Same face as verified account avatar” | Corpus = verified avatars + user uploads + one liveness frame only. **No open-web face search** |
| **Client-side liveness** | Blink / head-turn challenge | MediaPipe FaceMesh runs **in the browser**; only one verified frame is uploaded |
| **Skip-face path** | Fully usable without biometrics | Clears challenge + corpus; match endpoints refuse after skip |

**Definition of done (from the spec):**

1. Uploading a curated demo photo returns EXIF GPS + cached object findings in **under two seconds**.
2. Liveness challenge **passes and fails** correctly.
3. Skip-face leaves **no dangling** biometric / corpus state.

---

## Architecture (where code lives)

```
Browser (ui/ddu-ui)
  VisionPanel.tsx          one-click demos, upload, payoff cue (map/3D)
  LivenessChallenge.tsx    MediaPipe FaceMesh drop-in for Engineer A’s consent flow
        │  multipart / JSON
        ▼
ddu-mirror-intel  (:8120)
  mirror_intel/vision/
    exif.py          EXIF → lat/lon, make/model, timestamp
    cache.py         sha256 → precomputed objects / geo / face_boxes
    builders.py      Finding construction + reveal tokens + reversibility
    pipeline.py      analyze_upload() orchestration
    corpus.py        closed-corpus enroll / match (Rule 3)
    face.py          redaction preview (+ optional CompreFace HTTP)
    liveness.py      challenge / one-frame TTL / skip store
    routes.py        HTTP surface under /intel/vision/*
  data/vision_cache/
    index.json       hash → cached detections
    demo_*.jpg       curated demo photos (3–4)
```

Findings enter the session graph the same way any other producer does: built as `Finding` objects, then `session.add_findings(...)` (subject_ref forced to the verified seed — design rule 2).

Heavy models are **not** required at demo time. Say on stage:

> “Grounded-SAM-2 and GeoCLIP run async in our pipeline; these demo photos were pre-indexed by content hash.”

Nobody penalizes that. A live GPU failure on stage will.

---

## Finding types produced

| Type | Source | Typical state |
|---|---|---|
| `gps_exposure` | `exif:GPSInfo` | `confirmed` |
| `device_fingerprint` | `exif:Make/Model` | `confirmed` |
| `object_exposure` | `vision:grounded-sam-2:<prompt>` | `likely` |
| `location_inference` | `vision:geoclip` | **`hypothesis` only** |
| `face_link` | `face:compreface:closed_corpus` | `likely` |

Remediation / reversibility come from `mirror_intel.reversibility.classify` (design rule 7). Raw GPS and matched account labels are redacted in evidence rows; the vault holds the real values until reveal.

---

## HTTP API

All routes mount under the intel router prefix: **`/intel/vision/...`**.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/vision/demos` | List curated demo assets (metadata only) |
| `GET` | `/vision/demos/{slug}` | Download a demo JPEG for one-click upload |
| `POST` | `/vision/analyze` | Multipart photo → EXIF + cache → ingest findings |
| `POST` | `/vision/redaction-preview` | Face boxes / blur advice |
| `POST` | `/vision/face/enroll` | Enroll into closed corpus (`verified_avatar` \| `user_upload` \| `liveness_frame`) |
| `POST` | `/vision/face/match` | Match probe → `face_link` findings (corpus non-empty; fails if face path skipped) |
| `POST` | `/vision/liveness/start` | Issue blink / turn_left / turn_right challenge |
| `POST` | `/vision/liveness/complete` | Client pass/fail + optional single frame |
| `POST` | `/vision/liveness/skip` | Skip face; clear corpus + challenge |
| `GET` | `/vision/liveness/{session_id}` | Status / TTL remaining |

`POST /intel/findings/ingest` remains the generic door for any vision producer; `/vision/analyze` is the convenience path that builds findings and ingests them in one call.

### Analyze form fields

- `session_id` (required)
- `file` (required image)
- `platform` (optional, e.g. `instagram`)
- `parent_id` / `hop_depth` (optional graph placement; default parent = seed)

### Response highlights (`/vision/analyze`)

```json
{
  "cache_hit": true,
  "elapsed_ms": 1.07,
  "within_two_seconds": true,
  "exif": { "has_gps": true, "has_device": true },
  "disclosures": ["…pre-computed cache keyed by sha256…"],
  "redaction_preview": { "face_count": 1, "advice": "…" },
  "accepted": [ /* Finding[] */ ],
  "snapshot": { /* SessionSnapshot for UI */ }
}
```

---

## UI behaviour

1. Open Mirror at `http://localhost:5173` with `ddu-mirror-intel` on `:8120`.
2. Right rail → **Engineer C · Vision / Photo intelligence**.
3. Click a curated demo (or upload your own).
4. Panel shows cache timing + disclosure + redaction preview.
5. **Payoff cue** auto-switches the workspace to **Map** when GPS/location findings land (otherwise stays on **3D**), selects the highest-severity new finding, and offers **View map** / **View 3D** / **Dismiss**.
6. Optional **face step-up** expands `LivenessChallenge` (browser FaceMesh; Skip clears state).

`LivenessChallenge` is intentionally a drop-in module so Engineer A can mount it inside the biometric consent flow without depending on the rest of the Mirror shell.

---

## Demo assets

| Slug | File | Story |
|---|---|---|
| `vacation_plate` | `demo_vacation_plate.jpg` | Residential GPS + license plate + house number |
| `badge_selfie` | `demo_badge_selfie.jpg` | Workplace GPS + employee badge + faces |
| `stripped_street` | `demo_stripped_street.jpg` | **No EXIF** — GeoCLIP + street-sign objects still fire |
| `home_backyard` | `demo_home_backyard.jpg` | Home GPS + mailbox (stalker-persona critical) |

Regenerate (optional; needs `piexif`):

```powershell
cd "c:\Users\ahnaf\Downloads\DDU-main (1)\DDU-main"
.\.venv\Scripts\python.exe -m pip install -e "services\ddu-mirror-intel[vision-assets]"
.\.venv\Scripts\python.exe services\ddu-mirror-intel\scripts\generate_vision_demo_assets.py
```

Cache index: `services/ddu-mirror-intel/mirror_intel/data/vision_cache/index.json`  
Keys are **sha256 of the exact JPEG bytes**. Editing a demo image without regenerating the index breaks the cache hit.

---

## Design rules this slice enforces

1. **No free-text target** — photos are something the operator uploaded (consent = upload).
2. **No third-party traversal** — `subject_ref` forced to session seed on ingest; incidental faces are not extracted as people-findings (redaction preview only).
3. **Closed corpus only for face** — `CorpusViolation` on any non-allowlisted source (e.g. open-web scrape).
4. **Redact at the boundary** — GPS / matched account labels use reveal tokens.
5. **Ephemeral** — liveness frame has a short TTL; session wipe calls `cleanup_session_vision`.
6. **Skip must work** — face matching returns `409` after skip; corpus cleared.

---

## How to run (Mirror-only)

```powershell
# Terminal 1 — API
cd "c:\Users\ahnaf\Downloads\DDU-main (1)\DDU-main"
.\.venv\Scripts\python.exe -m pip install -e libs\ddu-py-common -e services\ddu-mirror-intel
.\.venv\Scripts\python.exe services\ddu-mirror-intel\app.py

# Terminal 2 — UI
cd ui\ddu-ui
npm install
npm run dev
```

Open http://localhost:5173.

Optional env (not required for the offline demo):

| Variable | Effect |
|---|---|
| `COMPREFACE_URL` / `COMPREFACE_API_KEY` | Live face detect for redaction preview |
| (ElevenLabs / Anthropic / HIBP) | Owned by other engineers — unused by C’s core path |

---

## How to test

### Automated (preferred)

```powershell
cd "c:\Users\ahnaf\Downloads\DDU-main (1)\DDU-main"
.\.venv\Scripts\python.exe -m pip install pytest python-multipart
.\.venv\Scripts\python.exe -m pytest services\ddu-mirror-intel\test_vision_engineer_c.py -q
```

Expected: **9 passed**. Coverage includes:

| Test | Asserts |
|---|---|
| `test_demo_assets_exist` | Cache index + demo JPEGs present |
| `test_exif_extracts_gps_from_demo_photo` | Live EXIF GPS on vacation photo |
| `test_analyze_demo_photo_under_two_seconds` | Cache hit, GPS + objects, geo=`hypothesis`, &lt;2s |
| `test_stripped_photo_emits_geo_hypothesis_without_gps` | No GPS finding; geo + objects still present |
| `test_closed_corpus_rejects_open_web_source` | Rule 3 hard fail |
| `test_face_enroll_and_match` | Closed-corpus → `face_link` |
| `test_liveness_pass_and_fail` | Fail keeps no frame; pass retains TTL’d frame |
| `test_skip_face_clears_dangling_state` | Corpus cleared; match → 409 |
| `test_wipe_clears_liveness` | Session DELETE drops liveness store |

### Manual demo checklist

1. Start API + UI (commands above).
2. Click **Vacation driveway photo**.
3. Confirm panel: `Cache hit`, `under 2s ✓`, findings ingested, disclosure text naming the hash cache.
4. Confirm workspace jumps toward **Map** (GPS) and the payoff cue appears.
5. Open evidence drawer on a GPS finding → value is `REDACTED` until reveal.
6. Click **EXIF-stripped street scene** → no GPS finding; location hypotheses still appear.
7. Expand **Optional face step-up** → Start challenge → Pass (or Simulate pass if MediaPipe/camera unavailable) → TTL shown.
8. Fail a challenge → no frame retained.
9. **Skip face path** → then face match must refuse; no leftover challenge.
10. **End & wipe** → session destroyed; liveness/corpus gone.

### Quick curl smoke (after creating a session)

```powershell
# Create session
curl -s http://localhost:8120/intel/session -H "Content-Type: application/json" -d "{\"session_id\":\"s_c\",\"handles\":[\"demo_operator\"]}"

# Analyze demo file
curl -s http://localhost:8120/intel/vision/analyze -F "session_id=s_c" -F "platform=instagram" -F "file=@services/ddu-mirror-intel/mirror_intel/data/vision_cache/demo_vacation_plate.jpg"
```

---

## Contracts handed to others

| Artifact | Consumer | Notes |
|---|---|---|
| Schema-valid vision findings | B (score/paths), D (3D/map/drawer) | Via ingest / analyze snapshot |
| Pre-computed `vision_cache` | Demo reliability | Disclose on stage |
| `LivenessChallenge` React module | A (consent flow) | Drop-in; skip path required |
| Closed-corpus enroll/match API | A/B for face_link story | Never open-web |

---

## What we deliberately do **not** ship here

- Live Grounded-SAM-2 / GeoCLIP inference on every upload (cache-only demo path; live services remain in Tier-2 `ddu-vision` / `ddu-geo` for the full DDU stack).
- Open-web face search (spec §12 — cannot be made defensive by inverting the subject).
- Treating GeoCLIP output as a confirmed address.
- Auto-promoting any vision finding past its verification state.

---

## File map (quick)

```
services/ddu-mirror-intel/
  mirror_intel/vision/          # this module
  mirror_intel/data/vision_cache/
  scripts/generate_vision_demo_assets.py
  test_vision_engineer_c.py
  CONTRACT.md                   # locked finding shape
ui/ddu-ui/src/
  VisionPanel.tsx
  LivenessChallenge.tsx
  mirror-api.ts                 # vision + liveness client helpers
docs/
  engineer-c-vision-biometrics.md   # this README
```
