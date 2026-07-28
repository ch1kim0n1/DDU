# DDU Mirror — Judge Demo Script

Target runtime: 4 minutes. Use the seeded demo session; cached or mock sources
must remain visibly disclosed.

## 0:00 — The promise

Say:

> “DDU Mirror starts with the only person we are allowed to investigate: you.
> It turns your own public footprint into a live, evidence-backed model of what
> an attacker could chain together.”

Point to the headline score, the threat-model selector, and the session posture.
Mention that the session is ephemeral.

## 0:25 — Explain the 3D grammar

Orbit the scene once.

Say:

> “Depth is distance from the identity I verified. Height and glow are
> severity. Colour is verification state. Pink links are attack paths — not
> decorative edges.”

Click a high-severity node. In the drawer, show confidence, provenance, and the
redacted evidence rows. Reveal one value and explain that the action is logged.

## 1:05 — Human control changes the graph

Open an agent proposal.

Say:

> “The agent has drafted an expansion. Nothing has run. It names the external
> system, the expected reach, and the hop it will add.”

Approve it. Pause while the new backend findings materialize in the WebGL
scene. If the source is cached, say so.

Next, select the Reddit hypothesis and press **That’s not me**.

Say:

> “The node disappears immediately, then the UI reconciles with a full server
> recompute. Descendants lose support, paths break, and the score is never
> patched by hand.”

## 2:05 — Remediation is honest

Select one reversible high-severity item and the breach. Run the remediation
simulation.

Say:

> “A reversible node goes dark and the projected score drops. The breach
> refuses. The underlying data is already mirrored, so the product offers a
> compensating control instead of pretending it can erase history.”

Point to the before/after score.

## 2:45 — Voice follows the live graph

Open **Ask Mirror** and click **Narrate current severity list**.

Say:

> “Narration is generated from the live non-rejected findings set. It will not
> read the node I rejected.”

If ElevenLabs credentials are configured, ask:

> “Which exposure should I fix first?”

Then point to the transcript status:

> “ElevenLabs performs speech-to-text. DDU scrubs identifiers before the
> question reaches the reasoning model, and scrubs the answer again before
> text-to-speech.”

If credentials are absent, use the typed question and explicitly describe the
browser-TTS fallback.

## 3:25 — Visible deletion

Press **End & wipe**.

Say:

> “Privacy is not a settings page. The backend returns the exact number of
> findings, raw vault values, proposals, and attack paths it destroyed — and
> the product makes that deletion visible.”

Close on:

> “Start with yourself. See what they’d see. Then break the path.”

## Recovery notes

- Backend: `python services/ddu-mirror-intel/app.py`
- UI: `npm run dev` from `ui/ddu-ui`
- Typed voice questions work without ElevenLabs.
- The Mirror intelligence service works without live HIBP, Sherlock, or an LLM
  and labels those paths as cached, mock, or offline.
- Do not describe the orchestration as a running LangGraph instance. It
  implements the same interrupt/resume contract as a direct state machine.
