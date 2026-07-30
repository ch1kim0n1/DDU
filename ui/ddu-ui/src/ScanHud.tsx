/**
 * Scan HUD — the "it's working" surface.
 *
 * Sits over the graph while approved steps execute, so the 3D scene
 * assembling itself has a caption. Without this, a scan that takes six
 * seconds looks identical to a scan that has silently stalled.
 *
 * Deliberately reports *node count* rather than a fake percentage on the
 * findings themselves: we genuinely don't know how many findings a step
 * will return until it returns them, and inventing a denominator to make
 * a smooth progress bar would be lying about certainty in a product
 * whose entire argument is calibrated confidence. The bar tracks steps
 * completed, which is a number we actually know.
 */

export type ScanStepState = "pending" | "running" | "done" | "skipped" | "failed";

export type ScanStep = {
  key: string;
  label: string;
  state: ScanStepState;
};

const GLYPH: Record<ScanStepState, string> = {
  pending: "○",
  running: "◐",
  done: "●",
  skipped: "—",
  failed: "×",
};

const CLASS: Record<ScanStepState, string> = {
  pending: "",
  running: "is-active",
  done: "is-done",
  skipped: "is-skipped",
  failed: "is-skipped",
};

type Props = {
  steps: ScanStep[];
  /** Nodes currently in the graph — ticks up as findings land. */
  nodeCount: number;
  onDismiss?: () => void;
};

export function ScanHud({steps, nodeCount, onDismiss}: Props) {
  const settled = steps.filter((s) => s.state === "done" || s.state === "skipped" || s.state === "failed");
  const pct = steps.length === 0 ? 0 : Math.round((settled.length / steps.length) * 100);
  const running = steps.find((s) => s.state === "running");
  const finished = settled.length === steps.length && steps.length > 0;

  return (
    <div className="scan-hud" role="status" aria-live="polite">
      <div className="scan-hud-top">
        <strong>
          {finished
            ? "Scan complete"
            : running
              ? running.label
              : "Waiting for your decision"}
        </strong>
        <span>
          <span className="scan-count">{nodeCount}</span> node{nodeCount === 1 ? "" : "s"} · {pct}%
        </span>
      </div>

      <div className="scan-bar">
        <i style={{width: `${pct}%`}} />
      </div>

      <div className="scan-steps">
        {steps.map((step) => (
          <div className={`scan-step ${CLASS[step.state]}`} key={step.key}>
            <span aria-hidden="true" className="glyph">
              {GLYPH[step.state]}
            </span>
            <span>{step.label}</span>
          </div>
        ))}
      </div>

      {finished && onDismiss ? (
        <div style={{marginTop: 12, textAlign: "right"}}>
          <button className="btn-quiet" onClick={onDismiss} type="button">
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}
