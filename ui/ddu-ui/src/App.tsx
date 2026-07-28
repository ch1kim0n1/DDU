import {useCallback, useEffect, useMemo, useRef, useState} from "react";

import {EvidenceDrawer} from "./EvidenceDrawer";
import {mirrorApi, websocketURL} from "./mirror-api";
import {MirrorMap} from "./MirrorMap";
import {Scene3D} from "./Scene3D";
import type {
  Finding,
  Proposal,
  SessionSnapshot,
  SimulationResult,
} from "./mirror-types";
import {VisionPanel} from "./VisionPanel";
import {VoicePanel} from "./VoicePanel";

const PERSONAS = [
  {id: "scammer", label: "Account takeover"},
  {id: "stalker", label: "Personal safety"},
  {id: "employer", label: "Employer screening"},
  {id: "state", label: "State actor"},
];

type CommandResult = {
  snapshot?: SessionSnapshot;
  payload?: Record<string, unknown>;
};

function collectDescendants(findings: Finding[], rootId: string) {
  const ids = new Set([rootId]);
  let changed = true;
  while (changed) {
    changed = false;
    findings.forEach((finding) => {
      if (finding.parent_id && ids.has(finding.parent_id) && !ids.has(finding.id)) {
        ids.add(finding.id);
        changed = true;
      }
    });
  }
  return ids;
}

function activeFindings(snapshot: SessionSnapshot | null) {
  return (
    snapshot?.findings.filter(
      (finding) =>
        finding.verification_state !== "rejected" &&
        finding.verification_state !== "contradicted",
    ) || []
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [view, setView] = useState<"scene" | "map">("scene");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [socketState, setSocketState] = useState<"connecting" | "live" | "fallback">(
    "connecting",
  );
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [fixedIds, setFixedIds] = useState<Set<string>>(new Set());
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [wipeState, setWipeState] = useState<{
    active: boolean;
    counts?: Record<string, number>;
    complete?: boolean;
  }>({active: false});
  const socketRef = useRef<WebSocket | null>(null);
  const pendingCommands = useRef(
    new Map<string, {resolve: (value: CommandResult) => void; reject: (reason: Error) => void}>(),
  );
  const sessionId = snapshot?.session_id || "";

  const connectSocket = useCallback((id: string) => {
    socketRef.current?.close();
    setSocketState("connecting");
    try {
      const socket = new WebSocket(websocketURL(id));
      socketRef.current = socket;
      socket.onopen = () => setSocketState("live");
      socket.onclose = () => setSocketState("fallback");
      socket.onerror = () => setSocketState("fallback");
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as {
          request_id?: string;
          snapshot?: SessionSnapshot;
          payload?: Record<string, unknown>;
          error?: string;
        };
        if (message.snapshot) setSnapshot(message.snapshot);
        if (message.request_id) {
          const pending = pendingCommands.current.get(message.request_id);
          if (pending) {
            pendingCommands.current.delete(message.request_id);
            if (message.error) pending.reject(new Error(message.error));
            else pending.resolve({snapshot: message.snapshot, payload: message.payload});
          }
        }
      };
    } catch {
      setSocketState("fallback");
    }
  }, []);

  const startDemo = useCallback(async () => {
    setLoading(true);
    setError("");
    const id = `sess_demo_${Date.now().toString(36)}`;
    try {
      await mirrorApi.health();
      const seedMocks =
        import.meta.env.VITE_MIRROR_SEED_MOCKS === "true" ||
        (import.meta.env.DEV && import.meta.env.VITE_MIRROR_SEED_MOCKS !== "false");
      const created = await mirrorApi.createSession(id, "scammer", seedMocks);
      setSnapshot(created.snapshot);
      const liveSessionId = created.session_id;
      connectSocket(liveSessionId);
      await mirrorApi.plan(liveSessionId);
      setSnapshot(await mirrorApi.snapshot(liveSessionId));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The Mirror intelligence service is unavailable.",
      );
    } finally {
      setLoading(false);
    }
  }, [connectSocket]);

  useEffect(() => {
    void startDemo();
    return () => socketRef.current?.close();
  }, [startDemo]);

  async function command(
    action: string,
    payload: Record<string, unknown>,
    fallback: () => Promise<unknown>,
  ) {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      const requestId = crypto.randomUUID();
      const response = new Promise<CommandResult>((resolve, reject) => {
        pendingCommands.current.set(requestId, {resolve, reject});
        window.setTimeout(() => {
          const pending = pendingCommands.current.get(requestId);
          if (pending) {
            pendingCommands.current.delete(requestId);
            reject(new Error("Live command timed out"));
          }
        }, 20_000);
      });
      socket.send(JSON.stringify({request_id: requestId, action, ...payload}));
      return response;
    }
    await fallback();
    if (sessionId) setSnapshot(await mirrorApi.snapshot(sessionId));
    return {};
  }

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${label} failed`);
    } finally {
      setBusy("");
    }
  }

  async function decideProposal(proposal: Proposal, decision: "approve" | "reject") {
    if (!snapshot) return;
    await run(`${decision}:${proposal.id}`, async () => {
      await command(
        decision === "approve" ? "proposal.approve" : "proposal.reject",
        {proposal_id: proposal.id},
        () =>
          decision === "approve"
            ? mirrorApi.approve(snapshot.session_id, proposal.id)
            : mirrorApi.rejectProposal(snapshot.session_id, proposal.id),
      );
      if (socketState !== "live") {
        setSnapshot(await mirrorApi.snapshot(snapshot.session_id));
      }
    });
  }

  async function rejectFinding(finding: Finding) {
    if (!snapshot) return;
    const optimistic = collectDescendants(snapshot.findings, finding.id);
    setHiddenIds(optimistic);
    setSelected(null);
    await run("reject-finding", async () => {
      try {
        const response = await command(
          "finding.reject",
          {finding_id: finding.id, reason: "That's not me"},
          () => mirrorApi.rejectFinding(snapshot.session_id, finding.id),
        );
        if (response.snapshot) setSnapshot(response.snapshot);
        else setSnapshot(await mirrorApi.snapshot(snapshot.session_id));
      } finally {
        setHiddenIds(new Set());
      }
    });
  }

  async function planExpansion() {
    if (!snapshot) return;
    await run("plan", async () => {
      await command(
        "agent.expand",
        {state: "TX", county: "Travis"},
        () => mirrorApi.plan(snapshot.session_id),
      );
      if (socketState !== "live") {
        setSnapshot(await mirrorApi.snapshot(snapshot.session_id));
      }
    });
  }

  async function changePersona(persona: string) {
    if (!snapshot) return;
    await run("persona", async () => {
      await command(
        "persona.change",
        {persona},
        () => mirrorApi.setPersona(snapshot.session_id, persona),
      );
      if (socketState !== "live") {
        setSnapshot(await mirrorApi.snapshot(snapshot.session_id));
      }
      setSimulation(null);
    });
  }

  async function simulate() {
    if (!snapshot || fixedIds.size === 0) return;
    await run("simulate", async () => {
      const result = await mirrorApi.simulate(snapshot.session_id, [...fixedIds]);
      setSimulation(result);
    });
  }

  async function wipe() {
    if (!snapshot) return;
    setWipeState({active: true});
    setSelected(null);
    setVoiceOpen(false);
    try {
      const response = await mirrorApi.wipe(snapshot.session_id);
      setWipeState({active: true, counts: response.destroyed, complete: true});
      window.setTimeout(() => {
        setSnapshot(null);
        setWipeState({active: false});
      }, 3000);
    } catch (reason) {
      setWipeState({active: false});
      setError(reason instanceof Error ? reason.message : "Session wipe failed");
    }
  }

  const findings = activeFindings(snapshot);
  const remediation = useMemo(
    () =>
      findings
        .filter((finding) => finding.type !== "seed_identity")
        .sort((a, b) => b.severity_score - a.severity_score)
        .slice(0, 6),
    [findings],
  );
  const refusedIds = new Set(simulation?.refused || []);
  const score = snapshot?.score;

  if (loading) {
    return (
      <div className="boot-screen">
        <div className="boot-mark">M</div>
        <p>Establishing an ephemeral Mirror session…</p>
        <span />
      </div>
    );
  }

  if (!snapshot || !score) {
    return (
      <div className="service-error">
        <span>DDU / MIRROR</span>
        <h1>The experience is built. The intelligence service is not running.</h1>
        <p>{error}</p>
        <code>python services/ddu-mirror-intel/app.py</code>
        <button onClick={() => void startDemo()} type="button">
          Retry connection
        </button>
      </div>
    );
  }

  return (
    <div className={`mirror-app ${wipeState.active ? "is-wiping" : ""}`}>
      <header className="mirror-header">
        <div className="mirror-brand">
          <span>M</span>
          <div>
            <strong>DDU / MIRROR</strong>
            <small>Start with yourself. See what they’d see.</small>
          </div>
        </div>
        <div className="session-posture">
          <span className={`live-dot ${socketState}`} />
          <div>
            <strong>{socketState === "live" ? "LIVE GRAPH" : "REST FALLBACK"}</strong>
            <small>Ephemeral · auto-destroy on exit</small>
          </div>
          <button onClick={() => void wipe()} type="button">
            End & wipe
          </button>
        </div>
      </header>

      <main className="mirror-main">
        <section className="risk-headline">
          <div className="score-ring">
            <svg viewBox="0 0 120 120" aria-hidden="true">
              <circle cx="60" cy="60" r="52" />
              <circle
                className={`score-arc band-${score.band}`}
                cx="60"
                cy="60"
                r="52"
                style={{strokeDashoffset: 327 - (327 * score.score) / 100}}
              />
            </svg>
            <div>
              <strong>{score.score}</strong>
              <span>/100</span>
            </div>
          </div>
          <div className="risk-copy">
            <p className="eyebrow">Your exposure score</p>
            <h1>
              {score.band === "critical" || score.band === "severe"
                ? "Your public footprint can be chained into an attack."
                : "Your exposure is visible — and partly fixable."}
            </h1>
            <p>
              {score.contributing_findings} live findings ·{" "}
              {Math.round(score.irreversible_share * 100)}% of weighted risk is
              irreversible
            </p>
          </div>
          <div className="before-after">
            <span>NOW</span>
            <strong>{score.score}</strong>
            <i>→</i>
            <span>AFTER FIXES</span>
            <strong>{simulation?.score_projected.score ?? "—"}</strong>
          </div>
        </section>

        <section className="workspace">
          <div className="canvas-column">
            <div className="workspace-toolbar">
              <div className="view-switch" role="tablist">
                <button
                  aria-selected={view === "scene"}
                  className={view === "scene" ? "active" : ""}
                  onClick={() => setView("scene")}
                  role="tab"
                >
                  3D exposure
                </button>
                <button
                  aria-selected={view === "map"}
                  className={view === "map" ? "active" : ""}
                  onClick={() => setView("map")}
                  role="tab"
                >
                  Map
                </button>
              </div>
              <div className="persona-control">
                <label htmlFor="persona">Threat model</label>
                <select
                  disabled={Boolean(busy)}
                  id="persona"
                  onChange={(event) => void changePersona(event.target.value)}
                  value={snapshot.persona}
                >
                  {PERSONAS.map((persona) => (
                    <option key={persona.id} value={persona.id}>
                      {persona.label}
                    </option>
                  ))}
                </select>
              </div>
              <button className="voice-launch" onClick={() => setVoiceOpen(true)}>
                <span>◉</span> Ask Mirror
              </button>
            </div>
            {view === "scene" ? (
              <Scene3D
                attackPaths={snapshot.attack_paths}
                findings={snapshot.findings}
                hiddenIds={hiddenIds}
                onSelect={setSelected}
                refusedIds={refusedIds}
                remediatedIds={fixedIds}
                selectedId={selected?.id}
              />
            ) : (
              <MirrorMap findings={snapshot.findings} onSelect={setSelected} />
            )}
            <div className="canvas-caption">
              <span>Height + glow = severity</span>
              <span>Z = hop depth from verified seed</span>
              <span>Pink edges = active attack path</span>
            </div>
          </div>

          <aside className="control-rail">
            <VisionPanel
              busy={Boolean(busy)}
              onPayoff={({preferredView, focusFinding}) => {
                setView(preferredView);
                if (focusFinding) setSelected(focusFinding);
              }}
              onSnapshot={setSnapshot}
              sessionId={snapshot.session_id}
              setBusy={setBusy}
              setError={setError}
            />

            <section className="rail-section approval-queue">
              <div className="rail-title">
                <div>
                  <p className="eyebrow">Human checkpoint</p>
                  <h2>Agent proposals</h2>
                </div>
                <span>{snapshot.pending_proposals.length}</span>
              </div>
              {snapshot.pending_proposals.length === 0 ? (
                <div className="rail-empty">
                  <p>No expansion can run without you.</p>
                  <button disabled={Boolean(busy)} onClick={() => void planExpansion()}>
                    Expand one hop
                  </button>
                </div>
              ) : (
                <div className="proposal-list">
                  {snapshot.pending_proposals.map((proposal) => (
                    <article className="proposal-card" key={proposal.id}>
                      <div>
                        <span>HOP {proposal.hop_depth}</span>
                        <span>
                          {proposal.touches_external.length ? "EXTERNAL" : "LOCAL ONLY"}
                        </span>
                      </div>
                      <h3>{proposal.title}</h3>
                      <p>{proposal.rationale}</p>
                      <small>{proposal.expected_findings}</small>
                      <div className="proposal-actions">
                        <button
                          className="approve"
                          disabled={Boolean(busy)}
                          onClick={() => void decideProposal(proposal, "approve")}
                        >
                          {busy === `approve:${proposal.id}` ? "Running…" : "Approve"}
                        </button>
                        <button
                          disabled={Boolean(busy)}
                          onClick={() => void decideProposal(proposal, "reject")}
                        >
                          Reject
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="rail-section remediation-sim">
              <div className="rail-title">
                <div>
                  <p className="eyebrow">What-if control</p>
                  <h2>Remediation sim</h2>
                </div>
                <span>{fixedIds.size}</span>
              </div>
              <div className="remediation-list">
                {remediation.map((finding) => (
                  <label
                    className={`${fixedIds.has(finding.id) ? "selected" : ""} ${
                      refusedIds.has(finding.id) ? "refused" : ""
                    }`}
                    key={finding.id}
                  >
                    <input
                      checked={fixedIds.has(finding.id)}
                      onChange={() => {
                        setFixedIds((current) => {
                          const next = new Set(current);
                          if (next.has(finding.id)) next.delete(finding.id);
                          else next.add(finding.id);
                          return next;
                        });
                        setSimulation(null);
                      }}
                      type="checkbox"
                    />
                    <span className={`severity-dot severity-${finding.severity}`} />
                    <span>
                      <strong>{finding.label}</strong>
                      <small>
                        {finding.reversible ? finding.remediation.effort : "irreversible"}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
              <button
                className="simulate-button"
                disabled={fixedIds.size === 0 || Boolean(busy)}
                onClick={() => void simulate()}
              >
                {busy === "simulate" ? "Simulating…" : "Simulate selected fixes"}
              </button>
              {simulation && (
                <div className="simulation-result">
                  <strong>
                    {simulation.score_now.score} → {simulation.score_projected.score}
                  </strong>
                  <span>
                    {simulation.refused.length
                      ? `${simulation.refused.length} permanent exposure${
                          simulation.refused.length > 1 ? "s" : ""
                        } refused to go dark.`
                      : "Every selected path breaks."}
                  </span>
                </div>
              )}
            </section>
          </aside>
        </section>

        <section className="lower-deck">
          <div className="attack-paths">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Chained risk</p>
                <h2>Attack paths</h2>
              </div>
              <span>{snapshot.attack_paths.length} active</span>
            </div>
            {snapshot.attack_paths.length === 0 ? (
              <p className="empty-copy">Rejected or remediated links have broken every path.</p>
            ) : (
              snapshot.attack_paths.slice(0, 3).map((path, index) => (
                <article key={path.id}>
                  <span>0{index + 1}</span>
                  <div>
                    <strong>{path.narrative}</strong>
                    <small>{path.terminal_impact}</small>
                  </div>
                  <meter max={1} min={0} value={path.feasibility} />
                </article>
              ))
            )}
          </div>
          <div className="activity-stream">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Evidence trail</p>
                <h2>Live decisions</h2>
              </div>
              <span>APPEND ONLY</span>
            </div>
            <ol>
              {snapshot.action_log_tail
                .slice(-5)
                .reverse()
                .map((entry) => (
                  <li key={entry.seq}>
                    <time>{new Date(entry.at).toLocaleTimeString([], {timeStyle: "short"})}</time>
                    <span className={`actor-${entry.actor}`}>{entry.actor}</span>
                    <p>{entry.detail}</p>
                  </li>
                ))}
            </ol>
          </div>
        </section>
        {error && <div className="toast-error">{error}</div>}
      </main>

      <EvidenceDrawer
        attribution={snapshot.attribution}
        finding={selected}
        onClose={() => setSelected(null)}
        onReject={(finding) => void rejectFinding(finding)}
        rejecting={busy === "reject-finding"}
        score={score}
        sessionId={snapshot.session_id}
      />
      {voiceOpen && (
        <VoicePanel onClose={() => setVoiceOpen(false)} sessionId={snapshot.session_id} />
      )}
      {wipeState.active && (
        <div className={`wipe-overlay ${wipeState.complete ? "complete" : ""}`}>
          <div className="wipe-grid" />
          <div className="wipe-message">
            <span className="wipe-icon">{wipeState.complete ? "✓" : "×"}</span>
            <p className="eyebrow">Ephemeral session</p>
            <h2>{wipeState.complete ? "Nothing remains." : "Destroying the graph…"}</h2>
            {wipeState.counts && (
              <p>
                {wipeState.counts.findings || 0} findings ·{" "}
                {wipeState.counts.vault_entries || 0} raw values ·{" "}
                {wipeState.counts.attack_paths || 0} attack paths destroyed
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
