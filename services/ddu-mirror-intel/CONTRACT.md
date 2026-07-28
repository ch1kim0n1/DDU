# DDU Mirror — Findings Contract v1.0.0

**Status: LOCKED.** Every module emits this; the 3D scene, evidence drawer,
voice agent, and scoring engine all consume it. Changes require a version bump
and a note in this file. No silent shape changes.

Source of truth: [`mirror_intel/schema.py`](mirror_intel/schema.py).
Live JSON Schema: `GET /intel/contract`.

---

## Finding

```jsonc
{
  "contract_version": "1.0.0",
  "id": "f_acct_github_4471",
  "parent_id": "f_seed",            // null for the seed
  "hop_depth": 2,                    // 3D Z axis: distance from verified seed

  "type": "gps_exposure",            // closed enum — see below
  "label": "Home GPS in vacation photo",
  "detail": "Longer explanation shown in the drawer",

  "verification_state": "confirmed", // confirmed|likely|hypothesis|contradicted|rejected
  "confidence": 0.95,

  "severity_base": 0.8,              // persona-INDEPENDENT
  "severity": "critical",            // persona-adjusted band
  "severity_score": 0.92,            // the number behind the band

  "reversible": false,
  "remediation": {
    "action": "Strip EXIF before posting; this image is already archived",
    "compensating": "Assume the address is known; harden physical + recovery",
    "effort": "low",                 // low|medium|high
    "permanent_note": "Public for >180 days — assume scraped."
  },

  "platform": "instagram",           // drives per-platform attribution
  "source": "exif:GPSInfo",          // where the value came from
  "method": "exifread v3.0",         // what produced it

  "evidence": [
    { "kind": "kv", "k": "lat/lon", "v": "REDACTED",
      "reveal_token": "rv_9f2c…", "redacted": true }
  ],
  "attack_path_ids": ["ap_731088"],

  "subject_ref": "subject:sess_abc",  // MUST equal the session's verified seed
  "origin": "agent",                  // agent|human|system
  "human_note": null,
  "timestamp": "2026-07-30T14:22:10Z"
}
```

### Field → consumer

| Field | Consumed by |
|---|---|
| `hop_depth` | 3D Z axis |
| `verification_state` | 3D node colour, voice phrasing |
| `severity` / `severity_score` | 3D node height & glow, remediation ranking |
| `reversible` | Remediation sim — whether the node can go dark |
| `platform` | Per-platform attribution chart |
| `attack_path_ids` | Lit path rendering |
| `parent_id` | Graph pruning on rejection |
| `evidence[].reveal_token` | Reveal-on-click |
| `origin` | Distinguishing human edits from agent output in the UI |

### Two validated invariants

1. **`reversible: false` requires `remediation.compensating`.** Enforced by a
   pydantic validator — a finding claiming permanence with no alternative
   fails construction. Design rule 7.
2. **`subject_ref` must equal the session's verified seed.** Checked in the
   workers and again in `Session.add_findings`. Design rule 2.

---

## Enums

**`type`** — closed set. Adding one means adding a persona weight
(`personas.py`), a reversibility rule (`reversibility.py`), and an
attack-path edge rule (`attack_paths.py`). Keeping it an enum makes those
omissions loud.

```
seed_identity  account   breach     gps_exposure  device_fingerprint
object_exposure  location_inference  face_link    handle_link
record_class   credential_reuse    employer_link  attacker_next_move
```

**`verification_state`** — `confirmed` · `likely` · `hypothesis` ·
`contradicted` · `rejected`. Never collapsed. Only `confirmed`, `likely`, and
`hypothesis` contribute to the score; `contradicted` and `rejected` stay in
the graph for the audit trail and contribute zero.

**`severity`** — `info` · `low` · `medium` · `high` · `critical`
**`effort`** — `low` · `medium` · `high`
**`origin`** — `agent` · `human` · `system`

---

## Proposal — the Track 3 object

```jsonc
{
  "id": "prop_01_a3f2",
  "session_id": "sess_abc",
  "step": "discovery.accounts",
  "title": "Search for accounts using your handle",
  "rationale": "Why the agent wants this — shown to the human before deciding",
  "expected_findings": "0-10 account findings, each individually rejectable",
  "touches_external": ["Sherlock (site availability checks)"],
  "inputs": { "hop_depth": 1 },      // REDACTED preview only
  "status": "awaiting_approval",     // → approved|edited|rejected|cancelled|executed|failed
  "human_edit": null,
  "human_reason": null,
  "decided_at": null,
  "created_at": "2026-07-30T14:20:00Z"
}
```

`inputs` carries a redacted preview only. Full step inputs are held out of
band in the orchestrator so a handle never reaches the action log or the wire.

---

## ActionLogEntry

```jsonc
{
  "seq": 14,                         // monotonic; a gap is detectable
  "session_id": "sess_abc",
  "at": "2026-07-30T14:22:10Z",
  "actor": "human",                  // agent|human|system
  "action": "human.rejected_finding",
  "subject": "f_acct_reddit_0912",
  "detail": "Scrubbed free text",
  "metadata": { "cascaded": ["f_link_x"], "broken_paths": ["ap_a1"] }
}
```

Action vocabulary is closed (`actionlog.py`). Prefixes carry meaning:
`agent.*` = the model proposed or acted, `human.*` = a person decided,
`system.*` = a guardrail fired.

---

## Interrupt / resume protocol (B → D)

```
POST /intel/scan/plan          → { event: "agent.awaiting_approval", proposals: [...] }
                                  ── nothing has run ──
POST /intel/scan/approve       → { findings: [...], score, attack_paths, attribution }
POST /intel/scan/edit          → same, plus applied_edit
POST /intel/scan/reject        → { proposal, findings_added: 0 }
POST /intel/scan/cancel        → kill switch; drops everything pending
```

Each proposal is also a LangGraph thread keyed by
`mirror:{session_id}:{proposal_id}`. Planning pauses at a dynamic
`interrupt`; approve/edit/reject resumes the stored checkpoint with
`Command(resume=...)`. Production checkpoints and encrypted session state use
Redis with the same TTL. SQLite is supported for durable single-worker
deployments and the in-memory saver is reserved for tests.

WebSocket event names Engineer A's stream should emit:
`finding.new` · `finding.updated` · `finding.rejected` · `score.changed` ·
`agent.awaiting_approval` · `session.wiped`

---

## Exposure score

`ScoreBreakdown` is a **pure function** of the live findings set and the
persona — `compute_score(findings, persona)`. Recomputed from scratch on every
mutation, never incremented.

```jsonc
{
  "score": 84,                       // 0-100
  "band": "severe",                  // minimal|moderate|elevated|severe|critical
  "persona": "scammer",
  "contributing_findings": 14,
  "suppressed_findings": 0,          // rejected + contradicted
  "irreversible_share": 0.391,
  "top_drivers": ["2019 forum breach", "Property deeds are public in your state"],
  "by_severity": { "critical": 4, "high": 3, "medium": 5, "low": 2, "info": 0 }
}
```

Three features read this simultaneously — persona re-ranking, the rejection
cascade, and the remediation simulation. **If anyone hardcodes or increments
it, all three break at once.**

Note `irreversible_share`: permanent exposures set a score floor, so marking
everything fixed still leaves a non-zero number. That's deliberate, and
`test_irreversible_exposure_sets_a_score_floor` asserts it.

---

## What a third-party model actually receives

`redaction.redact_finding` reduces a Finding to a field **allowlist** — a new
schema field is invisible to vendors until someone deliberately adds it here.

```json
{ "type": "gps_exposure", "severity": "critical", "severity_score": 0.92,
  "verification_state": "confirmed", "confidence": 0.95, "reversible": false,
  "platform": "instagram", "hop_depth": 2, "ref": "a1b2c3d4" }
```

Absent: `label`, `detail`, `evidence`, `source`, `subject_ref`, `human_note`,
`id`. Labels leak behaviour; sources leak devices; `ref` is a hash so answers
can be mapped back without the model learning the real id.

---

## Producer notes — Engineer C (vision)

Vision findings enter through `POST /intel/findings/ingest` (or the convenience
wrapper `POST /intel/vision/analyze`). Rules that must hold:

* `gps_exposure` / `device_fingerprint` — live EXIF; coords vaulted behind reveal tokens
* `object_exposure` — Grounded-SAM-2 **pre-computed**, method discloses cache
* `location_inference` — GeoCLIP **pre-computed**, always `verification_state=hypothesis`
* `face_link` — closed corpus only (verified avatars + user uploads); never open-web

---

## Changelog

### 1.0.0 — 2026-07-27
Initial lock. Contract frozen for the build.
