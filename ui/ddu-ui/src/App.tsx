import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  api,
  type Entity,
  type Evidence,
  type Investigation,
} from "./api";

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
  return (
    <div className="shell">
      <header className="masthead">
        <Link className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            DDU
          </span>
          <span>
            <strong>Digital Detective Unit</strong>
            <small>Evidence desk / Workflow A</small>
          </span>
        </Link>
        <div className="system-state">
          <i />
          Local operations
        </div>
      </header>
      <main>{children}</main>
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
      <section className="hero">
        <div>
          <p className="eyebrow">Investigation registry</p>
          <h1>Open a case.<br />Follow the evidence.</h1>
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
    </Shell>
  );
}

function InvestigationPage({id}: {id: string}) {
  const [investigation, setInvestigation] = useState<Investigation>();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [observations, setObservations] = useState<Entity[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [lineageCount, setLineageCount] = useState(0);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [caseData, entityData, observationData, lineageData, evidenceData] =
        await Promise.all([
          api.getInvestigation(id),
          api.listEntities(id),
          api.listObservations(id),
          api.listLineage(id),
          api.listEvidence(id),
        ]);
      setInvestigation(caseData);
      setEntities(entityData);
      setObservations(observationData);
      setLineageCount(lineageData.count);
      setEvidence(evidenceData);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load case");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function upload(file?: File) {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await api.uploadImage(id, file);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Processing failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Shell>
      <div className="case-header">
        <div>
          <Link className="back-link" to="/">← Registry</Link>
          <p className="eyebrow">Investigation file</p>
          <h1>{investigation?.name || "Loading case…"}</h1>
          <code>{id}</code>
        </div>
        <label className={`upload-control ${uploading ? "busy" : ""}`}>
          <input
            accept="image/*"
            disabled={uploading}
            onChange={(event) => void upload(event.target.files?.[0])}
            type="file"
          />
          <span>{uploading ? "Processing image…" : "＋ Upload image"}</span>
        </label>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <section className="metric-strip" aria-label="Investigation totals">
        <Metric label="Evidence" value={evidence.length} />
        <Metric label="Observations" value={observations.length} />
        <Metric label="All entities" value={entities.length} />
        <Metric label="Lineage runs" value={lineageCount} accent />
      </section>

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
  return (
    <div className={accent ? "metric accent" : "metric"}>
      <span>{label}</span>
      <strong>{value.toString().padStart(2, "0")}</strong>
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
