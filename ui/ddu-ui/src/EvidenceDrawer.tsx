import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {memo, useRef, useState} from "react";

import {useFocusTrap} from "./focusTrap";
import {mirrorApi} from "./mirror-api";
import type {
  Finding,
  PlatformAttribution,
  ScoreBreakdown,
} from "./mirror-types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ff5578",
  high: "#ff966b",
  medium: "#f2c66d",
  low: "#75bfff",
  info: "#718096",
};

type EvidenceDrawerProps = {
  finding: Finding | null;
  sessionId: string;
  score: ScoreBreakdown;
  attribution: PlatformAttribution[];
  onClose: () => void;
  onReject: (finding: Finding) => void;
  rejecting: boolean;
};

function EvidenceDrawerComponent({
  finding,
  sessionId,
  score,
  attribution,
  onClose,
  onReject,
  rejecting,
}: EvidenceDrawerProps) {
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [revealError, setRevealError] = useState("");
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useFocusTrap(drawerRef, Boolean(finding), onClose, closeRef);

  if (!finding) return null;

  const severityData = Object.entries(score.by_severity || {}).map(
    ([name, value]) => ({name, value}),
  );
  const attributionData = attribution.slice(0, 6).map((item) => ({
    platform: item.platform.replaceAll("_", " "),
    risk: Math.round(item.share * 100),
  }));

  async function reveal(key: string, token: string) {
    setRevealError("");
    try {
      const result = await mirrorApi.reveal(sessionId, finding!.id, key, token);
      setRevealed((current) => ({...current, [key]: result.value}));
    } catch (error) {
      setRevealError(error instanceof Error ? error.message : "Reveal refused");
    }
  }

  return (
    <aside
      ref={drawerRef}
      className="evidence-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="Evidence details"
    >
      <div className="drawer-handle" />
      <div className="drawer-header">
        <div>
          <span className={`severity-chip severity-${finding.severity}`}>
            {finding.severity}
          </span>
          <span className={`state-chip state-${finding.verification_state}`}>
            {finding.verification_state}
          </span>
          {finding.source === "mock:generator" && (
            <span className="data-tag mock">MOCK</span>
          )}
        </div>
        <button
          ref={closeRef}
          className="icon-button"
          onClick={onClose}
          aria-label="Close evidence drawer"
        >
          X
        </button>
      </div>
      <div className="drawer-scroll">
        <p className="eyebrow">{finding.type.replaceAll("_", " ")}</p>
        <h2>{finding.label}</h2>
        <p className="drawer-detail">{finding.detail}</p>

        <div className="drawer-metrics">
          <div>
            <span>Severity</span>
            <strong>{Math.round(finding.severity_score * 100)}</strong>
          </div>
          <div>
            <span>Confidence</span>
            <strong>{Math.round(finding.confidence * 100)}%</strong>
          </div>
          <div>
            <span>Hop</span>
            <strong>0{finding.hop_depth}</strong>
          </div>
        </div>

        <section className="drawer-section">
          <div className="section-title">
            <h3>Raw evidence</h3>
            <span>Redacted by default</span>
          </div>
          <div className="evidence-values">
            {finding.evidence.length === 0 && <p>No raw evidence attached.</p>}
            {finding.evidence.map((item) => {
              const visibleValue = revealed[item.k] || item.v;
              return (
                <div className="evidence-value" key={`${item.k}:${item.reveal_token}`}>
                  <span>{item.k.replaceAll("_", " ")}</span>
                  <code className={revealed[item.k] ? "revealed" : ""}>
                    {visibleValue}
                  </code>
                  {item.reveal_token && !revealed[item.k] && (
                    <button
                      onClick={() => void reveal(item.k, item.reveal_token!)}
                      type="button"
                    >
                      Hold to reveal
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          {revealError && <p className="inline-error">{revealError}</p>}
        </section>

        <section className="drawer-section">
          <div className="section-title">
            <h3>Risk composition</h3>
            <span>Live session</span>
          </div>
          <div className="chart-pair">
            <div className="mini-chart">
              <ResponsiveContainer height="100%" width="100%">
                <PieChart>
                  <Pie
                    data={severityData}
                    dataKey="value"
                    innerRadius={30}
                    outerRadius={52}
                    paddingAngle={3}
                  >
                    {severityData.map((entry) => (
                      <Cell
                        fill={SEVERITY_COLORS[entry.name] || "#718096"}
                        key={entry.name}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{background: "#111722", border: "1px solid #283244"}}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="attribution-chart">
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={attributionData} layout="vertical">
                  <XAxis domain={[0, 100]} hide type="number" />
                  <YAxis
                    axisLine={false}
                    dataKey="platform"
                    tick={{fill: "#8e9aaa", fontSize: 10}}
                    tickLine={false}
                    type="category"
                    width={68}
                  />
                  <Tooltip
                    contentStyle={{background: "#111722", border: "1px solid #283244"}}
                    cursor={{fill: "#151c28"}}
                  />
                  <Bar dataKey="risk" fill="#7b90ff" radius={[0, 8, 8, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        <section className="drawer-section remediation-copy">
          <div className="section-title">
            <h3>{finding.reversible ? "Recommended fix" : "Compensating control"}</h3>
            <span>{finding.remediation.effort} effort</span>
          </div>
          <p>{finding.remediation.action}</p>
          {!finding.reversible && (
            <div className="permanent-note">
              <strong>Cannot be undone</strong>
              <p>{finding.remediation.compensating}</p>
            </div>
          )}
        </section>

        <section className="drawer-section provenance">
          <h3>Attribution & provenance</h3>
          <dl>
            <div>
              <dt>Platform</dt>
              <dd>{finding.platform || "cross-platform"}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{finding.source}</dd>
            </div>
            <div>
              <dt>Method</dt>
              <dd>{finding.method}</dd>
            </div>
            <div>
              <dt>Origin</dt>
              <dd>{finding.origin}</dd>
            </div>
          </dl>
        </section>
      </div>
      {finding.type !== "seed_identity" &&
        finding.verification_state !== "rejected" && (
          <div className="drawer-actions">
            <button
              className="reject-finding"
              disabled={rejecting}
              onClick={() => onReject(finding)}
              type="button"
            >
              {rejecting ? "Recomputing..." : "That's not me"}
            </button>
            <span>Prunes dependent paths and recalculates the score.</span>
          </div>
        )}
    </aside>
  );
}

export const EvidenceDrawer = memo(EvidenceDrawerComponent, (prev, next) => {
  return (
    prev.finding?.id === next.finding?.id &&
    prev.finding?.verification_state === next.finding?.verification_state &&
    prev.rejecting === next.rejecting &&
    Boolean(prev.finding) === Boolean(next.finding)
  );
});
