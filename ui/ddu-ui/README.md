# DDU Mirror Experience

The Engineer D surface for DDU Mirror: a privacy-first React/TypeScript
experience backed by `services/ddu-mirror-intel`.

## What is implemented

- react-three-fiber scene driven by the locked findings contract
  - Z position = `hop_depth`
  - node height and emissive glow = `severity_score`
  - material colour = `verification_state`
  - lit pink edges = active attack paths
  - new findings animate into the scene after approval
- WebSocket approve/reject/expand command transport with REST fallback
- optimistic **That's not me** pruning, reconciled with the server snapshot
- remediation simulation with visible before/after score
  - reversible nodes go dark
  - irreversible nodes refuse and display `PERMANENT`
- redact-by-default evidence drawer and logged reveal-token exchange
- Recharts severity and platform-attribution views
- MapLibre privacy-safe map with deliberately jittered markers
- ElevenLabs STT/TTS voice path with local PII scrubbing and graph-grounded Q&A
- session-destruction animation driven by the real backend destroyed counts

## Run locally

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e libs\ddu-py-common -e services\ddu-mirror-intel
.\.venv\Scripts\python.exe services\ddu-mirror-intel\app.py
```

In another terminal:

```powershell
cd ui\ddu-ui
npm install
npm run dev
```

Open `http://localhost:5173`. The UI creates an ephemeral, judge-safe demo
session and connects to `http://localhost:8120` by default. Set
`VITE_MIRROR_API_URL` when the service lives elsewhere.

For production identity mode, the host login surface places its short-lived
OIDC/service assertion in `sessionStorage["ddu.identityToken"]`. The API
verifies the token and returns a server-generated high-entropy session id; the
UI never trusts the identifier fields in its demo request. Mock seeding is
disabled in production unless `VITE_MIRROR_SEED_MOCKS=true` is explicitly set.

## Voice configuration

Copy `services/ddu-mirror-intel/.env.example` to an ignored `.env` or provide
the variables through the process environment:

```text
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_TTS_MODEL=eleven_multilingual_v2
```

Without those credentials, typed questions remain grounded and functional,
and the browser's speech synthesis is used for playback. Microphone
transcription intentionally returns a configuration error rather than sending
audio anywhere unexpected.

## Voice privacy boundary

1. The user explicitly records an audio clip.
2. ElevenLabs transcribes that clip.
3. DDU scrubs the transcript with `mirror_intel.redaction.scrub_text`.
4. Only the scrubbed transcript and `redact_finding` allowlisted fields reach
   the voice-tier LLM.
5. The response is scrubbed again before TTS.
6. The browser receives only the scrubbed transcript.

Rejected and contradicted findings are removed from the grounding set, so a
new narration immediately stops reading them.

## Verification

```powershell
cd ui\ddu-ui
npm run build

cd ..\..
.\.venv\Scripts\python.exe -m pytest `
  services\ddu-mirror-intel\test_app.py `
  services\ddu-mirror-intel\test_engineer_d_contract.py -q
```

The dedicated Engineer D tests cover PII scrubbing, narration after rejection,
and WebSocket interrupt/resume materialization.
