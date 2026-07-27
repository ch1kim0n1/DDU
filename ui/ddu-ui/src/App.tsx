import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  api,
  getRole,
  setRole,
  type Entity,
  type Evidence,
  type Investigation,
  type Relationship,
  type TimelineEvent,
} from "./api";
import {GraphView} from "./GraphView";
import {MapView} from "./MapView";
import {Scene3D} from "./Scene3D";
import {TimelineView} from "./TimelineView";
import {MirrorOnboarding} from "./MirrorOnboarding";
import {
  useCaseMotion,
  useCountUp,
  useHomeMotion,
  useIntelLogMotion,
  useShellMotion,
  useTabPanelMotion,
} from "./useMotion";

function navigate(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function Link({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      className={className}
      href={to}
      onClick={(event) => {
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

function Shell({children}: {children: ReactNode}) {
  const rootRef = useRef<HTMLDivElement>(null);
  useShellMotion(rootRef);

  return (
    <div className="shell" ref={rootRef}>
      <header className="masthead">
        <Link className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            DDU
          </span>
          <span>
            <strong>Digital Detective Unit</strong>
            <small>Evidence desk / Phases 1–3</small>
          </span>
        </Link>
        <div className="system-state">
          <label>
            Role
            <select
              defaultValue={getRole()}
              onChange={(event) => { void setRole(event.target.value); }}
            >
              <option value="viewer">viewer</option>
              <option value="investigator">investigator</option>
              <option value="analyst">analyst</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <i />
          Local operations
        </div>
      </header>
      <main className="shell-main">{children}</main>
      <footer>
        <span>Observations remain observations.</span>
        <span>Evidence-backed · provenance-preserved</span>
      </footer>
    </div>
  );
}

function HomePage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const pageRef = useRef<HTMLDivElement>(null);
  useHomeMotion(pageRef, investigations.length);

  useEffect(() => {
    api.listInvestigations().then(setInvestigations).catch((reason: Error) => {
      setError(reason.message);
    });
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError("");
    try {
      const investigation = await api.createInvestigation(name.trim());
      navigate(`/investigations/${investigation.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Creation failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Shell>
      <div className="page-motion" ref={pageRef}>
        <section className="hero">
          <div>
            <p className="eyebrow">Investigation registry</p>
            <h1>Open a case. Follow the evidence.</h1>
            <p className="lede">
              Upload source imagery and review machine observations without
              collapsing detection into fact.
            </p>
          </div>
          <form className="create-card" onSubmit={create}>
            <span className="card-index">NEW / 01</span>
            <label htmlFor="investigation-name">Investigation name</label>
            <input
              id="investigation-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Operation name or case reference"
              autoComplete="off"
            />
            <button disabled={creating || !name.trim()} type="submit">
              {creating ? "Opening case…" : "Create investigation"}
            </button>
            {error && <p className="error">{error}</p>}
          </form>
        </section>

        <section className="registry">
          <div className="section-heading">
            <h2>Active investigations</h2>
            <span>{investigations.length.toString().padStart(2, "0")} files</span>
          </div>
          {investigations.length === 0 && !error ? (
            <div className="empty-state">
              <span>∅</span>
              No investigations registered in this session.
            </div>
          ) : (
            <div className="case-grid">
              {investigations.map((investigation, index) => (
                <Link
                  className="case-file"
                  key={investigation.id}
                  to={`/investigations/${investigation.id}`}
                >
                  <span className="case-number">
                    CASE {(index + 1).toString().padStart(3, "0")}
                  </span>
                  <h3>{investigation.name}</h3>
                  <code>{investigation.id}</code>
                  <time>{formatDate(investigation.created_at)}</time>
                  <b>Open file →</b>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </Shell>
  );
}

function InvestigationPage({id}: {id: string}) {
  const [investigation, setInvestigation] = useState<Investigation>();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [observations, setObservations] = useState<Entity[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [lineageCount, setLineageCount] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [username, setUsername] = useState("");
  const [sourceURL, setSourceURL] = useState("");
  const [typeName, setTypeName] = useState("");
  const [customTypes, setCustomTypes] = useState<string[]>([]);
  const [tab, setTab] = useState<"graph" | "map" | "timeline" | "intel" | "scene" | "list">("graph");
  const [intelLog, setIntelLog] = useState<string>("");
  const [scene, setScene] = useState<{nodes: Array<{id: string; label?: string; type?: string; x: number; y: number; z: number; confidence?: number}>; edges: Array<{id: string; source: string; target: string; confidence?: number}>}>({nodes: [], edges: []});
  const [playback, setPlayback] = useState<Array<{frame: number; narrative?: string}>>([]);
  const pageRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const intelLogRef = useRef<HTMLPreElement>(null);
  useCaseMotion(pageRef, Boolean(investigation));
  useTabPanelMotion(panelRef, tab);
  useIntelLogMotion(intelLogRef, intelLog);

  const load = useCallback(async () => {
    try {
      const [
        caseData,
        entityData,
        observationData,
        lineageData,
        evidenceData,
        relationshipData,
        timelineData,
        ontologyData,
      ] = await Promise.all([
        api.getInvestigation(id),
        api.listEntities(id),
        api.listObservations(id),
        api.listLineage(id),
        api.listEvidence(id),
        api.listRelationships(id),
        api.timeline(id),
        api.listOntologyTypes(id),
      ]);
      setInvestigation(caseData);
      setEntities(entityData);
      setObservations(observationData);
      setLineageCount(lineageData.count);
      setEvidence(evidenceData);
      setRelationships(relationshipData);
      setTimeline(timelineData);
      setCustomTypes(
        (ontologyData.entity_types || [])
          .filter((item: {custom?: boolean}) => item.custom)
          .map((item: {name: string}) => item.name),
      );
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load case");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await action();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${label} failed`);
    } finally {
      setBusy("");
    }
  }

  return (
    <Shell>
      <div className="page-motion case-motion" ref={pageRef}>
      <div className="case-header">
        <div>
          <Link className="back-link" to="/">← Registry</Link>
          <p className="eyebrow">Investigation file</p>
          <h1>{investigation?.name || "Loading case…"}</h1>
          <code>{id}</code>
        </div>
        <label className={`upload-control ${busy === "image" ? "busy" : ""}`}>
          <input
            accept="image/*"
            disabled={Boolean(busy)}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              void runAction("image", () => api.uploadImage(id, file));
            }}
            type="file"
          />
          <span>{busy === "image" ? "Processing image…" : "＋ Upload image"}</span>
        </label>
      </div>

      <section className="intake-grid">
        <form
          className="intake-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!username.trim()) return;
            void runAction("username", () => api.processUsername(id, username.trim()));
          }}
        >
          <label>
            Username workflow
            <input
              disabled={Boolean(busy)}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="handle"
              value={username}
            />
          </label>
          <button disabled={Boolean(busy) || !username.trim()} type="submit">
            {busy === "username" ? "Discovering…" : "Run discovery"}
          </button>
        </form>
        <form
          className="intake-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!sourceURL.trim()) return;
            void runAction("url", () => api.processURL(id, sourceURL.trim()));
          }}
        >
          <label>
            URL workflow
            <input
              disabled={Boolean(busy)}
              onChange={(event) => setSourceURL(event.target.value)}
              placeholder="https://"
              value={sourceURL}
            />
          </label>
          <button disabled={Boolean(busy) || !sourceURL.trim()} type="submit">
            {busy === "url" ? "Acquiring…" : "Collect / capture"}
          </button>
        </form>
        <div className="intake-actions">
          <button
            disabled={Boolean(busy)}
            onClick={() => void runAction("resolve", () => api.resolve(id))}
            type="button"
          >
            Resolve candidates
          </button>
          <button
            disabled={Boolean(busy)}
            onClick={() => void runAction("snapshot", () => api.createSnapshot(id, "manual"))}
            type="button"
          >
            Snapshot graph
          </button>
          <button
            disabled={Boolean(busy)}
            onClick={() => void runAction("report", () => api.generateReport(id))}
            type="button"
          >
            Generate report
          </button>
          <button
            disabled={Boolean(busy)}
            onClick={() =>
              void runAction("agent", () =>
                api.runAgent(id, "query", {query: "resolve locations and accounts"}),
              )
            }
            type="button"
          >
            NL agent plan
          </button>
        </div>
        <form
          className="intake-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!typeName.trim()) return;
            void runAction("ontology", () =>
              api.createOntologyType(id, {
                name: typeName.trim(),
                description: "Custom investigation type",
                parent_type: "ENTITY_TYPE_OBJECT",
              }),
            );
            setTypeName("");
          }}
        >
          <label>
            Custom ontology type
            <input
              disabled={Boolean(busy)}
              onChange={(event) => setTypeName(event.target.value)}
              placeholder="drone"
              value={typeName}
            />
          </label>
          <button disabled={Boolean(busy) || !typeName.trim()} type="submit">
            {busy === "ontology" ? "Registering…" : "Add entity type"}
          </button>
          {customTypes.length > 0 && (
            <small>{customTypes.join(", ")}</small>
          )}
        </form>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="metric-strip" aria-label="Investigation totals">
        <Metric label="Evidence" value={evidence.length} />
        <Metric label="Observations" value={observations.length} />
        <Metric label="Relationships" value={relationships.length} />
        <Metric label="Lineage runs" value={lineageCount} accent />
      </section>

      <div className="tab-bar" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "graph"}
          className={tab === "graph" ? "active" : ""}
          onClick={() => setTab("graph")}
        >
          Graph
        </button>
        <button
          role="tab"
          aria-selected={tab === "map"}
          className={tab === "map" ? "active" : ""}
          onClick={() => setTab("map")}
        >
          Map
        </button>
        <button
          role="tab"
          aria-selected={tab === "timeline"}
          className={tab === "timeline" ? "active" : ""}
          onClick={() => setTab("timeline")}
        >
          Timeline
        </button>
        <button
          role="tab"
          aria-selected={tab === "intel"}
          className={tab === "intel" ? "active" : ""}
          onClick={() => setTab("intel")}
        >
          Intel
        </button>
        <button
          role="tab"
          aria-selected={tab === "scene"}
          className={tab === "scene" ? "active" : ""}
          onClick={() => {
            setTab("scene");
            void runAction("scene", async () => {
              const [sceneData, playbackData] = await Promise.all([
                api.intelScene(id),
                api.intelPlayback(id),
              ]);
              setScene({nodes: sceneData.nodes || [], edges: sceneData.edges || []});
              setPlayback(playbackData.frames || []);
            });
          }}
        >
          3D / Playback
        </button>
        <button
          role="tab"
          aria-selected={tab === "list"}
          className={tab === "list" ? "active" : ""}
          onClick={() => setTab("list")}
        >
          List
        </button>
      </div>

      <div className="tab-stage" ref={panelRef}>
      {tab === "graph" && (
        <section className="tab-panel graph-panel">
          {entities.length === 0 ? (
            <p className="panel-empty">No entities to graph yet.</p>
          ) : (
            <GraphView entities={entities} relationships={relationships} />
          )}
        </section>
      )}

      {tab === "map" && (
        <section className="tab-panel map-panel">
          <MapView observations={observations} />
        </section>
      )}

      {tab === "timeline" && (
        <section className="tab-panel timeline-panel">
          <TimelineView events={timeline} />
        </section>
      )}

      {tab === "intel" && (
        <section className="tab-panel intel-panel">
          <div className="intel-actions">
            {[
              ["identity/resolve", "Identity resolve"],
              ["aliases", "Aliases"],
              ["social-circle", "Social circle"],
              ["household", "Household"],
              ["property", "Property records"],
              ["records/fuse", "Public-record fusion"],
              ["employment", "Employment graph"],
              ["location/current", "Current location"],
              ["location/history", "Location history"],
              ["location/fuse", "Location fusion"],
              ["pattern-of-life", "Pattern of life"],
              ["life-events", "Life events"],
              ["relationship/strength", "Relationship strength"],
              ["temporal/diff", "Temporal diff"],
              ["assets", "Assets"],
            ].map(([path, label]) => (
              <button
                disabled={Boolean(busy)}
                key={path}
                onClick={() =>
                  void runAction(path, async () => {
                    const result = await api.intel(id, path, {subject: investigation?.name || "subject"});
                    setIntelLog(JSON.stringify(result, null, 2));
                  })
                }
                type="button"
              >
                {label}
              </button>
            ))}
            <button
              disabled={Boolean(busy)}
              onClick={() =>
                void runAction("web-history", async () => {
                  const result = await api.intel(id, "web-history", {
                    subject: investigation?.name || "subject",
                    url: "https://example.com/profile",
                  });
                  setIntelLog(JSON.stringify(result, null, 2));
                })
              }
              type="button"
            >
              Web history / deleted content
            </button>
          </div>
          <pre className="intel-log" ref={intelLogRef}>
            {intelLog || "Run a post-MVP intel capability to inspect hypotheses."}
          </pre>
        </section>
      )}

      {tab === "scene" && (
        <section className="tab-panel scene-panel">
          <Scene3D edges={scene.edges} nodes={scene.nodes} />
          <ol className="playback-list">
            {playback.map((frame) => (
              <li key={frame.frame}>
                <strong>Frame {frame.frame}</strong>
                <span>{frame.narrative}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {tab === "list" && (
        <div className="dashboard-grid">
          <section className="panel evidence-panel">
            <div className="section-heading">
              <h2>Evidence register</h2>
              <span>Immutable source objects</span>
            </div>
            {evidence.length === 0 ? (
              <p className="panel-empty">Upload an image to begin analysis.</p>
            ) : (
              <div className="evidence-list">
                {evidence.map((item) => (
                  <Link
                    key={item.id}
                    to={`/investigations/${id}/evidence/${encodeURIComponent(item.id)}`}
                    className="evidence-row"
                  >
                    <div className="thumb-placeholder">IMG</div>
                    <div>
                      <strong>{item.mime_type}</strong>
                      <code>{shortHash(item.id)}</code>
                      <small>{formatBytes(item.size_bytes)} · {item.acquisition_method}</small>
                    </div>
                    <span>View →</span>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section className="panel observations-panel">
            <div className="section-heading">
              <h2>Extracted observations</h2>
              <span>Unverified machine output</span>
            </div>
            {observations.length === 0 ? (
              <p className="panel-empty">No observations recorded.</p>
            ) : (
              <div className="observation-list">
                {observations.map((item) => (
                  <ObservationCard entity={item} key={item.id} />
                ))}
              </div>
            )}
          </section>

          <section className="panel relationships-panel">
            <div className="section-heading">
              <h2>Candidate relationships</h2>
              <span>Human verification required</span>
            </div>
            {relationships.length === 0 ? (
              <p className="panel-empty">Run resolve to propose candidates.</p>
            ) : (
              <div className="relationship-list">
                {relationships.map((rel) => (
                  <article className="relationship-card" key={rel.id}>
                    <strong>{rel.relationship_type}</strong>
                    <code>
                      {shortHash(rel.source_entity_id)} → {shortHash(rel.target_entity_id)}
                    </code>
                    <span>{rel.verification_state || "PENDING"}</span>
                    <div className="verify-actions">
                      <button
                        disabled={Boolean(busy)}
                        onClick={() =>
                          void runAction("verify", () =>
                            api.verifyRelationship(id, rel.id, "VERIFICATION_STATE_VERIFIED"),
                          )
                        }
                        type="button"
                      >
                        Verify
                      </button>
                      <button
                        disabled={Boolean(busy)}
                        onClick={() =>
                          void runAction("verify", () =>
                            api.verifyRelationship(id, rel.id, "VERIFICATION_STATE_REJECTED"),
                          )
                        }
                        type="button"
                      >
                        Reject
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
      </div>
      </div>
    </Shell>
  );
}

function EvidencePage({
  investigationId,
  evidenceId,
}: {
  investigationId: string;
  evidenceId: string;
}) {
  const [evidence, setEvidence] = useState<Evidence>();
  const [observations, setObservations] = useState<Entity[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getEvidence(investigationId, evidenceId),
      api.listObservations(investigationId, evidenceId),
    ])
      .then(([evidenceData, observationData]) => {
        setEvidence(evidenceData);
        setObservations(observationData);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [evidenceId, investigationId]);

  return (
    <Shell>
      <div className="evidence-header">
        <Link className="back-link" to={`/investigations/${investigationId}`}>
          ← Investigation
        </Link>
        <p className="eyebrow">Evidence viewer</p>
        <h1>{shortHash(evidenceId)}</h1>
        <code>{evidenceId}</code>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="viewer-grid">
        <section className="image-stage">
          {evidence?.download_url ? (
            <img alt="Uploaded evidence" src={evidence.download_url} />
          ) : (
            <span>Retrieving evidence…</span>
          )}
        </section>
        <aside className="metadata-panel">
          <p className="eyebrow">Source record</p>
          <dl>
            <Metadata label="MIME" value={evidence?.mime_type} />
            <Metadata label="Size" value={evidence && formatBytes(evidence.size_bytes)} />
            <Metadata label="Acquired" value={evidence && formatDate(evidence.acquired_at)} />
            <Metadata label="Method" value={evidence?.acquisition_method} />
            {Object.entries(evidence?.metadata || {}).map(([key, value]) => (
              <Metadata key={key} label={key.replaceAll("_", " ")} value={value} />
            ))}
          </dl>
        </aside>
      </div>
      <section className="panel linked-observations">
        <div className="section-heading">
          <h2>Observations from this evidence</h2>
          <span>{observations.length} linked records</span>
        </div>
        <div className="observation-list">
          {observations.map((item) => (
            <ObservationCard entity={item} key={item.id} />
          ))}
        </div>
      </section>
    </Shell>
  );
}

function Metric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  const valueRef = useRef<HTMLElement | null>(null);
  useCountUp(valueRef, value);
  return (
    <div className={accent ? "metric accent" : "metric"}>
      <span>{label}</span>
      <strong ref={(node) => { valueRef.current = node; }}>
        {value.toString().padStart(2, "0")}
      </strong>
    </div>
  );
}

function ObservationCard({entity}: {entity: Entity}) {
  const type = entity.attributes.observation_type?.replace("OBSERVATION_TYPE_", "") || "UNKNOWN";
  return (
    <article className="observation-card">
      <div>
        <span className={`type-tag type-${type.toLowerCase()}`}>{type}</span>
        <strong>{entity.attributes.label || "Unlabelled observation"}</strong>
      </div>
      <span className="confidence">
        {Math.round(Number(entity.attributes.detector_confidence || 0) * 100)}%
      </span>
      <code>{shortHash(entity.id)}</code>
    </article>
  );
}

function Metadata({label, value}: {label: string; value?: string}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

function shortHash(value: string) {
  const clean = value.replace("sha256:", "");
  return clean.length > 18 ? `${clean.slice(0, 10)}…${clean.slice(-6)}` : clean;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  const evidenceMatch = path.match(/^\/investigations\/([^/]+)\/evidence\/(.+)$/);
  if (path === "/mirror") {
    return <MirrorOnboarding />;
  }
  if (evidenceMatch) {
    return (
      <EvidencePage
        investigationId={decodeURIComponent(evidenceMatch[1])}
        evidenceId={decodeURIComponent(evidenceMatch[2])}
      />
    );
  }
  const investigationMatch = path.match(/^\/investigations\/([^/]+)$/);
  if (investigationMatch) {
    return <InvestigationPage id={decodeURIComponent(investigationMatch[1])} />;
  }
  return <HomePage />;
}
