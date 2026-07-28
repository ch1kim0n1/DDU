# ddu-mirror-intel — Engineer B

Discovery, intelligence, and the human-in-the-loop agent for **DDU Mirror**.

> *Start with yourself. See what they'd see.*

This is the defensive carve-out of the DDU engine: same lifecycle, inverted
subject. Nothing in this service can be pointed at a person who has not proven
control of the identity being scanned.

---

## Track 3 — Human-in-the-Loop AI Assistant

The hackathon track asks for three things. They aren't features bolted on here;
they're the shape of the service.

| Track 3 requirement | Where it lives |
|---|---|
| **AI draft or suggestion** | `orchestrator.plan()` drafts `Proposal` objects. Nothing runs. |
| **Approve / edit / reject flow** | `approve()`, `edit_and_approve()`, `reject()` — plus `cancel()` as a kill switch. `execute()` raises `PermissionError` on anything not approved or edited. |
| **Simple action log** | `actionlog.ActionLog` — append-only, sequenced, PII-scrubbed at write time, and it records **refusals and rejections**, not just successes. |

The load-bearing line of the whole service is in `orchestrator.execute`:

```python
if proposal.status not in (ProposalStatus.APPROVED, ProposalStatus.EDITED):
    raise PermissionError(...)
```

There is no bypass flag. Every finding in the graph traces back through that
check to a human decision recorded in the log.

---

## Quick start

```bash
# ddu-py-common must be installed FIRST — installing this service alone will
# try to resolve it from PyPI, where it does not exist.
pip install -e libs/ddu-py-common
pip install -e services/ddu-mirror-intel

python services/ddu-mirror-intel/app.py     # :8120
pytest services/ddu-mirror-intel/test_app.py -q
```

Everything runs with **no API keys and no network**. Missing `anthropic` drops
the LLM layer to a deterministic offline provider; missing `HIBP_API_KEY` and
missing `sherlock` fall back to cached demo data. All three states are
disclosed in the response payloads rather than hidden — see *Honesty flags*.

## Engineer C — Vision & Biometrics

Full documentation: [`docs/engineer-c-vision-biometrics.md`](../../docs/engineer-c-vision-biometrics.md).

```bash
# Curated demo JPEGs + hash cache ship in mirror_intel/data/vision_cache/
# Regenerate (optional):
pip install -e '.[vision-assets]'
python scripts/generate_vision_demo_assets.py
```

| Endpoint | Role |
|---|---|
| `POST /intel/vision/analyze` | EXIF + hash-cached SAM-2/GeoCLIP → ingest |
| `GET  /intel/vision/demos` | List curated demo assets |
| `GET  /intel/vision/demos/{slug}` | Download a demo JPEG |
| `POST /intel/vision/redaction-preview` | Face boxes / blur advice |
| `POST /intel/vision/face/enroll` | Closed-corpus enroll (verified avatar / upload) |
| `POST /intel/vision/face/match` | Face-link findings (closed corpus only) |
| `POST /intel/vision/liveness/start\|complete\|skip` | Client FaceMesh challenge + skip path |

UI drop-ins: `ui/ddu-ui/src/LivenessChallenge.tsx`, `VisionPanel.tsx`.

Tests: `pytest services/ddu-mirror-intel/test_vision_engineer_c.py -q`

| Env var | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables real model calls. Absent → offline provider. |
| `HIBP_API_KEY` | Enables live breach lookup. Absent → cached demo data, labelled. |
| `MIRROR_FORCE_OFFLINE=1` | Forces the deterministic provider (demo safety). |
| `MIRROR_PERSONA_WEIGHTS` | Path to Engineer A's persona matrix JSON. |
| `MIRROR_REVEAL_SECRET` | HMAC secret for reveal tokens. Absent → per-process random. |
| `MIRROR_REDIS_URL` | Enables encrypted TTL sessions, Redis checkpoints, and Pub/Sub. |
| `MIRROR_SESSION_ENCRYPTION_KEY` | Required 32-byte base64 key whenever Redis is enabled. |
| `MIRROR_IDENTITY_REQUIRED=1` | Requires a signed OIDC/service identity assertion. |
| `MIRROR_REQUIRE_LIVE_PROVIDERS=1` | Refuses cached HIBP/Sherlock fallbacks. |
| `MIRROR_REQUIRE_ELEVENLABS=1` | Makes both ElevenLabs STT and TTS deployment requirements. |
| `COMPREFACE_URL` / `COMPREFACE_API_KEY` | Optional live face detect; closed-corpus match works without them. |

---

## What Engineer B hands to everyone else

| Artifact | For | Where |
|---|---|---|
| **Findings contract v1** | A, C, D | `mirror_intel/schema.py`, `GET /intel/contract` |
| **Mock findings generator** | C, D | `mirror_intel/mock.py`, `GET /intel/mock/findings` |
| **Redaction layer** | D (voice) | `mirror_intel.redaction.scrub_text`, `redact_finding` |
| **Interrupt / resume protocol** | D | `agent.awaiting_approval` → `POST /intel/scan/approve` |
| **Scoring & pruning endpoints** | D | `POST /intel/findings/reject`, `POST /intel/simulate` |
| **Persona matrix shape** | A | `mirror_intel/personas.py` — `load_persona_weights()` takes A's JSON verbatim |

**Ship the contract and the mock generator first.** They're small, and they
unblock two people each.

---

## Design rules, and where each one is actually enforced

The spec lists seven non-negotiables. Five are enforced in this service, in
code rather than in a doc:

| Rule | Enforcement |
|---|---|
| 1 — No verified control, no scan | `guardrails.assert_self` is the first statement of every discovery entry point. No worker signature accepts a bare string target. |
| 2 — No third-party traversal | `guardrails.suppress_third_party` + `scrub_incidental_identifiers`. `Session.add_findings` re-checks `subject_ref` at the door. |
| 4 — Redact at the boundary | `redaction.assert_no_raw_pii` runs on every outbound LLM payload and **raises rather than sends**. Field allowlist, not denylist. |
| 6 — Untrusted text never touches a tool-enabled model | `Tier.QUARANTINE` binds no tools; `quarantine.parse_untrusted` returns data only, and returns **no findings by design**. |
| 7 — Nothing irreversible is claimed reversible | A pydantic validator on `Finding` — `reversible=False` without a compensating control fails construction. |

Rules 3 (closed-corpus face) and 5 (ephemeral sessions) belong to C and A
respectively; `Session.wipe()` is B's half of rule 5.

---

## Module map

```
mirror_intel/
├── schema.py          # LOCKED findings contract v1.0.0
├── personas.py        # persona × finding_type weight matrix
├── guardrails.py      # fail-closed identity assertion, 3rd-party suppression
├── redaction.py       # the outbound trust boundary + reveal tokens
├── llm.py             # complete(messages, tier) — 4 tiers, offline fallback
├── quarantine.py      # tool-less parse + deterministic injection classifier
├── reversibility.py   # reversible/irreversible by type + age
├── scoring.py         # exposure score — PURE FUNCTION, recomputed on mutation
├── attack_paths.py    # chaining over parent_id + type pivots, narrated
├── attribution.py     # per-platform, weighted by severity not count
├── correction.py      # "that's not me" cascade prune, edit, restore
├── remediation.py     # severity ÷ effort ranking + persona-specific copy
├── records.py         # public records advisor — NO lookups, NO scraping
├── actionlog.py       # append-only HITL log
├── identity.py        # OIDC/JWKS or signed-service identity verification
├── session.py         # encrypted Redis TTL store + local memory backend
├── events.py          # Redis Pub/Sub or local WebSocket fan-out
├── workflow.py        # checkpointed LangGraph interrupt/resume runtime
├── orchestrator.py    # propose → approve/edit/reject → execute
├── mock.py            # schema-valid fake findings for C and D
├── api.py             # FastAPI router, mounts at /intel
└── data/              # curated jurisdictions + cached demo results
```

---

## The demo beats this service backs

| Demo beat | Endpoint |
|---|---|
| Persona pick, then re-rank later | `POST /intel/persona` — *same findings*, different order |
| **Try to scan someone else → fails closed** | Any scan with an unverified identifier → `403` with a written explanation |
| Agent proposes → human approves → graph blooms | `POST /intel/scan/plan` → `/approve` |
| Attack path lights up | `snapshot.attack_paths[].narrative` |
| **Reject a false positive → graph prunes, score corrects** | `POST /intel/findings/reject` |
| Mark fixed → nodes go dark; **breach refuses** | `POST /intel/simulate` → `refused[]` |
| **Prompt injection caught and quarantined** | `POST /intel/quarantine/classify` (works offline) |
| End session → everything visibly deletes | `DELETE /intel/session/{id}` returns destroyed counts |

### The refusal demo, from a terminal

```bash
curl -s -X POST localhost:8120/intel/scan/edit \
  -H 'content-type: application/json' \
  -d '{"session_id":"s1","proposal_id":"prop_01_ab12",
       "changes":{"email":"someone.else@example.com"}}' | jq .detail
```

```json
{
  "error": "target_refused",
  "explanation": "DDU Mirror can only scan identities this session has proven control of. There is no free-text target field in this product. ...",
  "design_rule": "1 — no verified control, no scan"
}
```

Note the request that gets refused is an **edit** — the one arm of
approve/edit/reject that takes user input. The identity gate runs on the
edited value, so "edit" cannot become a free-text target field through the
back door. `test_editing_toward_an_unverified_target_still_gets_refused`
covers exactly that.

---

## Honesty flags

Every degraded path is disclosed in its own payload rather than hidden:

| Flag | Meaning |
|---|---|
| `offline: true` | Remediation copy came from the deterministic provider, not a model. |
| `method: "HIBP cached demo data (disclosed)"` | Breach data is cached — say so on stage. |
| `method: "... [cached]"` | Sherlock results came from cache, not a live enumeration. |
| `is_mock: true` / `source: "mock:generator"` | Fabricated data. Label it in the UI. |
| `no_lookup_performed: true` | The records advisor retrieved nothing, by design. |

---

## Two decisions worth defending

**LangGraph owns the approval cursor.** Every proposal arms a stable graph
thread and pauses at a dynamic `interrupt`. Approve, edit, or reject resumes
that checkpoint with `Command(resume=...)`; discovery runs only in the node
after the interrupt. Redis is the production checkpointer, SQLite is the
durable single-worker option, and memory remains available for isolated tests.
Raw decision inputs stay in the separately encrypted session store rather than
the searchable checkpoint index.

**Linkability is hand-rolled, not Splink.** Probabilistic record linkage is
right for reconciling millions of records and wrong for scoring four signals
across a handful of accounts. The hand-rolled scorer has no training step and
— the part that matters — shows its working in the evidence drawer. "These two
accounts share an avatar hash and a distinctive bio phrase" is auditable in a
way a match weight is not.

---

## Test suite

70 tests, all passing, no network required. They're organized around the
claims the product makes on stage — if one fails, a sentence in the pitch has
become false. That's the bar for inclusion, rather than coverage for its own
sake.

Two worth knowing about:

- `test_there_is_no_free_text_target_field` greps the generated OpenAPI schema
  for a `target` field. It fails if anyone adds one.
- `test_irreversible_exposure_sets_a_score_floor` asserts that marking
  *everything* fixed still leaves a non-zero score, because part of it is
  permanent.
