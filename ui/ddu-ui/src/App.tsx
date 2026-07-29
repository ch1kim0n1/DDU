import {
  lazy,
  Suspense,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {track} from "./analytics";
import {CookieConsent, storageAllowed} from "./CookieConsent";
import {
  EXPECTED_API_VERSION,
  mirrorApi,
  RateLimitError,
  SessionExpiredError,
  websocketURL,
  type HealthResponse,
} from "./mirror-api";
import {OnboardingWizard, type OnboardingData} from "./OnboardingWizard";
import type {
  Finding,
  Proposal,
  SessionSnapshot,
  SimulationResult,
} from "./mirror-types";
import {ToastStack, useToastQueue} from "./ToastQueue";

const Scene3D = lazy(() =>
  import("./Scene3D").then((module) => ({default: module.Scene3D})),
);
const MirrorMap = lazy(() =>
  import("./MirrorMap").then((module) => ({default: module.MirrorMap})),
);
const VisionPanel = lazy(() =>
  import("./VisionPanel").then((module) => ({default: module.VisionPanel})),
);
const VoicePanel = lazy(() =>
  import("./VoicePanel").then((module) => ({default: module.VoicePanel})),
);
const EvidenceDrawer = lazy(() =>
  import("./EvidenceDrawer").then((module) => ({default: module.EvidenceDrawer})),
);

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
  const viteProd = import.meta.env.VITE_MIRROR_ENV === "production";
  const [productionLocked, setProductionLocked] = useState(viteProd);
  const [dataMode, setDataMode] = useState<"mock" | "real">(() => {
    if (viteProd) return "real";
    if (!storageAllowed()) return "mock";
    const stored = localStorage.getItem("ddu.dataMode");
    return stored === "real" ? "real" : "mock";
  });
  const [showWizard, setShowWizard] = useState(false);
  const [onboardingData, setOnboardingData] = useState<OnboardingData | null>(null);
  const [socketState, setSocketState] = useState<"connecting" | "live" | "fallback">(
    "connecting",
  );
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [fixedIds, setFixedIds] = useState<Set<string>>(new Set());
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [providerOpen, setProviderOpen] = useState(false);
  const [providerHealth, setProviderHealth] = useState<HealthResponse | null>(null);
  const [providerSummary, setProviderSummary] = useState<Record<string, string>>({});
  const findingsListRef = useRef<HTMLDivElement>(null);
  const [activityFilter, setActivityFilter] = useState<"all" | "human" | "agent" | "system">(
    "all",
  );
  const [activityQuery, setActivityQuery] = useState("");
  const [envBanner, setEnvBanner] = useState("");
  const [apiVersionWarn, setApiVersionWarn] = useState("");
  const {toasts, push: pushToast, dismiss: dismissToast} = useToastQueue();
  const deferredSnapshot = useDeferredValue(snapshot);
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
      socket.onclose = (event) => {
        setSocketState("fallback");
        if (event.code === 1008 || event.code === 1011) {
          setSessionExpired(true);
        }
      };
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

  const startDemo = useCallback(
    async (mode: "mock" | "real", data?: OnboardingData | null) => {
      setLoading(true);
      setError("");
      const id = `sess_${mode}_${Date.now().toString(36)}`;
      try {
        const health = await mirrorApi.health();
        setProviderHealth(health);
        const backendProd =
          health.env === "production" || health.mirror_env === "production";
        if (backendProd) setProductionLocked(true);
        if ((backendProd || viteProd) && mode === "mock") {
          pushToast("Mock data is not available in production mode", "warn");
          setDataMode("real");
          setShowWizard(true);
          setLoading(false);
          return;
        }
        const seedMocks = mode === "mock" && !backendProd && !viteProd;
        const persona = data?.persona || "scammer";
        const emails = data?.emails || ["demo@ddu-mirror.local"];
        const handles = data?.handles || ["demo_operator"];
        const accountUrls = data?.accountUrls || [];
        const created = await mirrorApi.createSession(
          id,
          persona,
          seedMocks,
          emails,
          handles,
          accountUrls,
        );
        setSnapshot(created.snapshot);
        const liveSessionId = created.session_id;
        sessionStorage.setItem("ddu.sessionId", liveSessionId);
        connectSocket(liveSessionId);
        await mirrorApi.plan(
          liveSessionId,
          data?.state || "TX",
          data?.county || "Travis",
        );
        setSnapshot(await mirrorApi.snapshot(liveSessionId));
        track("session_started", {mode});
      } catch (reason) {
        if (reason instanceof SessionExpiredError) {
          setSessionExpired(true);
        } else if (reason instanceof RateLimitError) {
          pushToast("Too many requests, please wait", "warn");
        } else {
          const message =
            reason instanceof Error
              ? reason.message
              : "The Mirror intelligence service is unavailable.";
          if (/mock/i.test(message) && /production/i.test(message)) {
            pushToast("Mock data is not available in production mode", "warn");
            setProductionLocked(true);
            setDataMode("real");
            setShowWizard(true);
          } else {
            setError(message);
            pushToast(message, "error");
          }
        }
      } finally {
        setLoading(false);
      }
    },
    [connectSocket, pushToast, viteProd],
  );

  useEffect(() => {
    if (!import.meta.env.VITE_MIRROR_API_URL) {
      setEnvBanner(
        "Using default backend URL (localhost:8120). Set VITE_MIRROR_API_URL for production.",
      );
    }
    if (!import.meta.env.VITE_SENTRY_DSN) {
      console.warn("VITE_SENTRY_DSN is not set — error tracking is disabled.");
    }
    async function loadHealth() {
      try {
        const health = await mirrorApi.health();
        setProviderHealth(health);
        const env = health.env || health.mirror_env || "";
        if (env === "production" || import.meta.env.VITE_MIRROR_ENV === "production") {
          setProductionLocked(true);
          setDataMode((current) => {
            if (current === "mock") {
              setShowWizard(true);
              return "real";
            }
            return current;
          });
        }
        const apiVersion = (health as HealthResponse & {api_version?: string}).api_version;
        if (apiVersion && !String(apiVersion).startsWith(EXPECTED_API_VERSION)) {
          setApiVersionWarn(
            `The backend is running an older API version (expected ${EXPECTED_API_VERSION}, got ${apiVersion}). Some features may not work. Please contact support.`,
          );
        }
      } catch {
        /* boot continues */
      }
      try {
        const summary = await mirrorApi.providers();
        setProviderSummary(summary as Record<string, string>);
        setProviderHealth((current) => current);
      } catch {
        /* optional */
      }
    }
    void loadHealth();
    const timer = window.setInterval(() => void loadHealth(), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const sortedFindings = useMemo(
    () =>
      activeFindings(deferredSnapshot).sort(
        (a, b) => b.severity_score - a.severity_score,
      ),
    [deferredSnapshot],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!findingsListRef.current?.contains(document.activeElement) && document.activeElement !== findingsListRef.current) {
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      if (!sortedFindings.length) return;
      const index = sortedFindings.findIndex((finding) => finding.id === selected?.id);
      const nextIndex =
        event.key === "ArrowDown"
          ? Math.min(sortedFindings.length - 1, Math.max(0, index) + 1)
          : Math.max(0, (index < 0 ? 0 : index) - 1);
      setSelected(sortedFindings[nextIndex] || null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected?.id, sortedFindings]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const existing = sessionStorage.getItem("ddu.sessionId");
      if (existing) {
        try {
          const restored = await mirrorApi.snapshot(existing);
          if (cancelled) return;
          setSnapshot(restored);
          connectSocket(existing);
          setLoading(false);
          return;
        } catch {
          sessionStorage.removeItem("ddu.sessionId");
        }
      }
      if (dataMode === "mock") {
        void startDemo("mock");
      } else if (onboardingData) {
        void startDemo("real", onboardingData);
      } else {
        setShowWizard(true);
        setLoading(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
      socketRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataMode]);

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
      if (reason instanceof SessionExpiredError) {
        setSessionExpired(true);
      } else if (reason instanceof RateLimitError) {
        pushToast("Too many requests, please wait", "warn");
      } else if (reason instanceof Error && reason.message.includes("timed out")) {
        pushToast("The server is taking longer than expected. Checking status...", "warn");
        if (sessionId) {
          void mirrorApi
            .snapshot(sessionId)
            .then((next) => {
              setSnapshot(next);
              pushToast("Action completed successfully.", "info");
            })
            .catch(() => pushToast("The action timed out. Please try again.", "error"));
        }
      } else {
        const message = reason instanceof Error ? reason.message : `${label} failed`;
        setError(message);
        pushToast(message, "error");
      }
    } finally {
      setBusy("");
    }
  }

  function restartSession() {
    setSessionExpired(false);
    setSnapshot(null);
    setSelected(null);
    setSimulation(null);
    setFixedIds(new Set());
    setHiddenIds(new Set());
    sessionStorage.removeItem("ddu.sessionId");
    if (dataMode === "mock") void startDemo("mock");
    else if (onboardingData) void startDemo("real", onboardingData);
    else setShowWizard(true);
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
    const confirmed = window.confirm(
      "This will permanently destroy all findings. This cannot be undone. Continue?",
    );
    if (!confirmed) return;
    setWipeState({active: true});
    setSelected(null);
    setVoiceOpen(false);
    try {
      const response = await mirrorApi.wipe(snapshot.session_id);
      sessionStorage.removeItem("ddu.sessionId");
      track("wipe_completed", {mode: dataMode});
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

  function switchDataMode(mode: "mock" | "real") {
    if (mode === dataMode || Boolean(busy) || wipeState.active) return;
    if (mode === "mock" && productionLocked) {
      pushToast("Mock mode is not available in production", "warn");
      return;
    }
    if (storageAllowed()) localStorage.setItem("ddu.dataMode", mode);
    sessionStorage.removeItem("ddu.sessionId");
    setDataMode(mode);
    setSelected(null);
    setSimulation(null);
    setFixedIds(new Set());
    setHiddenIds(new Set());
    setOnboardingData(null);
    setShowWizard(false);
    setSnapshot(null);
    socketRef.current?.close();
  }

  function handleWizardComplete(data: OnboardingData) {
    setOnboardingData(data);
    setShowWizard(false);
    void startDemo("real", data);
  }

  function handleWizardCancel() {
    setShowWizard(false);
    switchDataMode("mock");
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

  if (showWizard) {
    return (
      <OnboardingWizard
        busy={loading}
        error={error}
        onComplete={handleWizardComplete}
        onCancel={handleWizardCancel}
      />
    );
  }

  if (loading) {
    return (
      <div className="boot-screen">
        <div className="boot-mark">M</div>
        <p>Establishing an ephemeral Mirror session...</p>
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
        <button onClick={() => void startDemo(dataMode, onboardingData)} type="button">
          Retry connection
        </button>
      </div>
    );
  }

  return (
    <div className={`mirror-app ${wipeState.active ? "is-wiping" : ""}`}>
      {envBanner ? (
        <div className="data-mode-banner" role="status">
          <strong>Config</strong>
          <span>{envBanner}</span>
        </div>
      ) : null}
      {apiVersionWarn ? (
        <div className="data-mode-banner" role="status">
          <strong>API</strong>
          <span>{apiVersionWarn}</span>
        </div>
      ) : null}
      <header className="mirror-header">
        <div className="mirror-brand">
          <span>M</span>
          <div>
            <strong>DDU / MIRROR</strong>
            <small>Start with yourself. See what they'd see.</small>
          </div>
        </div>
        <div className="header-controls">
          <div className="help-menu">
            <button
              type="button"
              aria-label="Help"
              className="help-button"
              onClick={() => setHelpOpen((open) => !open)}
            >
              ?
            </button>
            {helpOpen && (
              <div className="help-popover" role="dialog">
                <p>Need help? Email support@ddu-mirror.local</p>
                <a href="/docs/user-guide.md" target="_blank" rel="noopener noreferrer">
                  User guide
                </a>
              </div>
            )}
          </div>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              void mirrorApi
                .exportSession(snapshot.session_id)
                .then((data) => {
                  const blob = new Blob([JSON.stringify(data, null, 2)], {
                    type: "application/json",
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `ddu-mirror-${snapshot.session_id}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                })
                .catch((err) =>
                  pushToast(err instanceof Error ? err.message : "Export failed", "error"),
                );
            }}
          >
            Download my data
          </button>
          <button type="button" className="secondary" onClick={() => window.print()}>
            Print report
          </button>
          <div className="data-mode-toggle" role="group" aria-label="Data source">
            <button
              className={dataMode === "mock" ? "active mock" : ""}
              disabled={Boolean(busy) || wipeState.active || productionLocked}
              onClick={() => switchDataMode("mock")}
              title={
                productionLocked
                  ? "Mock mode is not available in production"
                  : "Use synthetic demo findings"
              }
              type="button"
            >
              Mock
            </button>
            <button
              className={dataMode === "real" ? "active real" : ""}
              disabled={Boolean(busy) || wipeState.active}
              onClick={() => switchDataMode("real")}
              type="button"
            >
              Real
            </button>
          </div>
          <div className="provider-status">
            <button
              type="button"
              className="provider-dot-button"
              aria-label="Provider status"
              onClick={() => setProviderOpen((open) => !open)}
              title="Provider status"
            >
              <span
                className={`provider-dot ${
                  providerHealth?.state === "UNHEALTHY"
                    ? "bad"
                    : providerHealth?.state === "DEGRADED"
                      ? "warn"
                      : "ok"
                }`}
              />
            </button>
            {providerOpen ? (
              <div className="provider-popover" role="dialog">
                <p>LLM: {providerSummary.llm || providerSummary.local || "unknown"}</p>
                <p>
                  ElevenLabs:{" "}
                  {providerSummary.elevenlabs === "available"
                    ? "Available"
                    : "Not configured (using browser TTS)"}
                </p>
                <p>
                  Redis:{" "}
                  {providerSummary.redis === "connected" ? "Connected" : "In-memory / disabled"}
                </p>
                {providerHealth?.dependencies
                  ? Object.entries(providerHealth.dependencies).map(([name, state]) => (
                      <p key={name}>
                        {name}: {state}
                      </p>
                    ))
                  : null}
              </div>
            ) : null}
          </div>
          <div className="session-posture">
            <span className={`live-dot ${socketState}`} />
            <div>
              <strong>{socketState === "live" ? "LIVE GRAPH" : "REST FALLBACK"}</strong>
              <small>Ephemeral, auto-destroy on exit</small>
            </div>
            <button
              aria-label="End session and destroy all data"
              onClick={() => void wipe()}
              type="button"
            >
              End & wipe
            </button>
          </div>
        </div>
      </header>
      {dataMode === "mock" && (
        <div className="data-mode-banner" role="status">
          <strong>MOCK DATA</strong>
          <span>
            Synthetic findings for development and demo. Not real intelligence.
            Toggle to Real for live discovery.
          </span>
        </div>
      )}
      {dataMode === "real" && (
        <div className="data-mode-banner real" role="status">
          <strong>REAL DATA</strong>
          <span>
            Live discovery mode. Graph starts empty - approve proposals to
            collect real findings.
          </span>
        </div>
      )}

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
              <strong
                aria-live="polite"
                className="score-value"
                tabIndex={0}
                title={`Permanent: ${Math.round(score.irreversible_share * 100)}, findings: ${score.contributing_findings}, band: ${score.band}`}
              >
                {score.score}
              </strong>
              <span>/100</span>
              <div className="score-tooltip" role="tooltip">
                <p>
                  Permanent share: {Math.round(score.irreversible_share * 100)} · Live findings:{" "}
                  {score.contributing_findings}
                </p>
                <p>
                  Drivers: {(score.top_drivers || []).slice(0, 3).join(", ") || "n/a"}
                </p>
                {simulation ? (
                  <p>
                    {simulation.score_projected.score - simulation.score_now.score >= 0 ? "+" : ""}
                    {simulation.score_projected.score - simulation.score_now.score} since last
                    simulation
                  </p>
                ) : null}
              </div>
            </div>
          </div>
          <div className="risk-copy">
            <p className="eyebrow">Your exposure score</p>
            <h1>
              {score.band === "critical" || score.band === "severe"
                ? "Your public footprint can be chained into an attack."
                : "Your exposure is visible - and partly fixable."}
            </h1>
            <p>
              {score.contributing_findings} live findings,{" "}
              {Math.round(score.irreversible_share * 100)}% of weighted risk is
              irreversible
            </p>
          </div>
          <div className="before-after">
            <span>NOW</span>
            <strong>{score.score}</strong>
            <i>-&gt;</i>
            <span>AFTER FIXES</span>
            <strong>{simulation?.score_projected.score ?? "-"}</strong>
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
              <button
                aria-label="Open voice assistant"
                className="voice-launch"
                onClick={() => setVoiceOpen(true)}
              >
                <span>&bull;</span> Ask Mirror
              </button>
            </div>
            <div
              ref={findingsListRef}
              className="findings-focus-region"
              tabIndex={0}
              aria-label="Findings view. Use Up and Down arrows to move between findings."
            >
              <Suspense fallback={<div className="scene-loading">Loading view...</div>}>
                {view === "scene" ? (
                  <Scene3D
                    attackPaths={(deferredSnapshot || snapshot).attack_paths}
                    findings={(deferredSnapshot || snapshot).findings}
                    hiddenIds={hiddenIds}
                    onSelect={setSelected}
                    refusedIds={refusedIds}
                    remediatedIds={fixedIds}
                    selectedId={selected?.id}
                  />
                ) : (
                  <MirrorMap
                    findings={(deferredSnapshot || snapshot).findings}
                    onSelect={setSelected}
                  />
                )}
              </Suspense>
            </div>
            <div className="canvas-caption">
              <span>Height + glow = severity</span>
              <span>Z = hop depth from verified seed</span>
              <span>Pink edges = active attack path</span>
            </div>
          </div>

          <aside className="control-rail">
            <Suspense fallback={<div className="scene-loading">Loading vision...</div>}>
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
            </Suspense>

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
                  <button
                    aria-label="Generate new expansion proposals"
                    disabled={Boolean(busy)}
                    onClick={() => void planExpansion()}
                  >
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
                        {dataMode === "mock" && (
                          <span className="data-tag mock">MOCK</span>
                        )}
                      </div>
                      <h3>{proposal.title}</h3>
                      <p>{proposal.rationale}</p>
                      <small>{proposal.expected_findings}</small>
                      <div className="proposal-diff">
                        <p>
                          Will search:{" "}
                          {Object.values(proposal.inputs || {})
                            .flatMap((value) =>
                              Array.isArray(value)
                                ? value.map(String)
                                : value
                                  ? [String(value)]
                                  : [],
                            )
                            .slice(0, 6)
                            .join(", ") || proposal.touches_external.join(", ") || "session identifiers"}
                        </p>
                        <p>This expansion takes approximately 30 seconds</p>
                        <p>
                          {proposal.touches_external.length
                            ? "Elevated risk - touches external services"
                            : "Low risk - searches public records only"}
                        </p>
                      </div>
                      <div className="proposal-actions">
                        <button
                          aria-label={`Approve proposal ${proposal.title}`}
                          className="approve"
                          disabled={Boolean(busy)}
                          onClick={() => void decideProposal(proposal, "approve")}
                        >
                          {busy === `approve:${proposal.id}` ? "Running..." : "Approve"}
                        </button>
                        <button
                          aria-label={`Reject proposal ${proposal.title}`}
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
                        {finding.source === "mock:generator" && " - mock"}
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
                {busy === "simulate" ? "Simulating..." : "Simulate selected fixes"}
              </button>
              {simulation && (
                <div className="simulation-result">
                  <strong>
                    {simulation.score_now.score} -&gt; {simulation.score_projected.score}
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
            {dataMode === "mock" && (
              <p className="data-note">Paths below are synthetic mock chains.</p>
            )}
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
            <div className="activity-filters" role="group" aria-label="Filter activity">
              {(
                [
                  ["all", "All"],
                  ["human", "Human actions"],
                  ["agent", "Agent actions"],
                  ["system", "System"],
                ] as const
              ).map(([filter, label]) => (
                <button
                  key={filter}
                  type="button"
                  className={activityFilter === filter ? "active" : ""}
                  onClick={() => setActivityFilter(filter)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="activity-search">
              <span className="sr-only">Search activity</span>
              <input
                type="search"
                placeholder="Filter activity…"
                value={activityQuery}
                onChange={(event) => setActivityQuery(event.target.value)}
              />
            </label>
            <ol aria-live="polite">
              {snapshot.action_log_tail.length === 0 ? (
                <li className="empty-copy">
                  No actions yet. Approve a proposal to begin discovery.
                </li>
              ) : (
                snapshot.action_log_tail
                  .filter(
                    (entry) =>
                      activityFilter === "all" || entry.actor === activityFilter,
                  )
                  .filter((entry) =>
                    activityQuery.trim()
                      ? `${entry.detail} ${entry.action} ${entry.actor}`
                          .toLowerCase()
                          .includes(activityQuery.trim().toLowerCase())
                      : true,
                  )
                  .slice(-40)
                  .reverse()
                  .slice(0, 12)
                  .map((entry) => (
                    <li key={entry.seq}>
                      <time>
                        {new Date(entry.at).toLocaleTimeString([], {timeStyle: "short"})}
                      </time>
                      <span className={`actor-${entry.actor}`}>{entry.actor}</span>
                      <p>{entry.detail}</p>
                    </li>
                  ))
              )}
            </ol>
          </div>
        </section>
        <div className="print-report" aria-hidden="true">
          <h1>DDU Mirror report</h1>
          <p>
            Session {snapshot.session_id} · Persona {snapshot.persona} ·{" "}
            {new Date().toLocaleString()}
          </p>
          <h2>Score</h2>
          <p>
            Total {score.score}/100 · Permanent share{" "}
            {Math.round(score.irreversible_share * 100)}% · Findings{" "}
            {score.contributing_findings}
          </p>
          <h2>Findings</h2>
          <ol>
            {[...snapshot.findings]
              .sort((a, b) => b.severity_score - a.severity_score)
              .map((finding) => (
                <li key={finding.id}>
                  <strong>{finding.label}</strong> — {finding.severity} ·{" "}
                  {Math.round(finding.confidence * 100)}% · {finding.remediation?.action || "n/a"}
                </li>
              ))}
          </ol>
          <h2>Remediation checklist</h2>
          <ul>
            {sortedFindings.map((finding) => (
              <li key={`remed-${finding.id}`}>
                <input type="checkbox" readOnly /> {finding.label} (
                {finding.reversible ? finding.remediation.effort : "irreversible"})
              </li>
            ))}
          </ul>
          <h2>Attack paths</h2>
          <ul>
            {snapshot.attack_paths.map((path) => (
              <li key={path.id}>
                {path.narrative} — {path.terminal_impact}
              </li>
            ))}
          </ul>
        </div>
        <footer className="mirror-footer">
          <a href="/privacy-policy.html" target="_blank" rel="noopener noreferrer">
            Privacy Policy
          </a>
          <a href="/terms-of-service.html" target="_blank" rel="noopener noreferrer">
            Terms of Service
          </a>
          <a href="mailto:support@ddu-mirror.local">Contact</a>
          <a href="mailto:support@ddu-mirror.local?subject=DDU%20Mirror%20Bug%20Report">
            Report a bug
          </a>
        </footer>
        <ToastStack toasts={toasts} onDismiss={dismissToast} />
      </main>

      <Suspense fallback={null}>
        <EvidenceDrawer
          attribution={snapshot.attribution}
          finding={selected}
          onClose={() => setSelected(null)}
          onReject={(finding) => void rejectFinding(finding)}
          rejecting={busy === "reject-finding"}
          score={score}
          sessionId={snapshot.session_id}
        />
      </Suspense>
      {voiceOpen && (
        <Suspense fallback={null}>
          <div data-no-plausible="true">
            <VoicePanel onClose={() => setVoiceOpen(false)} sessionId={snapshot.session_id} />
          </div>
        </Suspense>
      )}
      {wipeState.active && (
        <div className={`wipe-overlay ${wipeState.complete ? "complete" : ""}`}>
          <div className="wipe-grid" />
          <div className="wipe-message">
            <span className="wipe-icon">{wipeState.complete ? "OK" : "X"}</span>
            <p className="eyebrow">Ephemeral session</p>
            <h2>{wipeState.complete ? "Nothing remains." : "Destroying the graph..."}</h2>
            {wipeState.counts && (
              <p>
                {wipeState.counts.findings || 0} findings,{" "}
                {wipeState.counts.vault_entries || 0} raw values,{" "}
                {wipeState.counts.attack_paths || 0} attack paths destroyed
              </p>
            )}
            {wipeState.complete && (
              <div className="wipe-feedback">
                <p>Before you go, was this useful?</p>
                <button
                  type="button"
                  onClick={() => {
                    track("wipe_completed", {useful: 1});
                    pushToast("Thanks for the feedback", "info");
                  }}
                >
                  Thumbs up
                </button>
                <button
                  type="button"
                  onClick={() => {
                    track("wipe_completed", {useful: 0});
                    pushToast("Thanks for the feedback", "info");
                  }}
                >
                  Thumbs down
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {sessionExpired && (
        <div className="session-expired-modal" role="dialog" aria-modal="true">
          <div className="session-expired-card">
            <h2>Your session has expired</h2>
            <p>Start a new one?</p>
            <div className="session-expired-actions">
              <button type="button" onClick={restartSession}>
                Restart
              </button>
              <button type="button" onClick={() => setSessionExpired(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      <CookieConsent onDecline={() => setDataMode("mock")} />
    </div>
  );
}
