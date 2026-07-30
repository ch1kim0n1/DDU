/**
 * Landing stage — the first thing anyone sees.
 *
 * Two jobs, in this order:
 *
 * 1. Say what this is in one line, because "an OSINT engine pointed at
 *    yourself" is not self-evident from a graph.
 * 2. State the refusals *before* asking for a camera. Someone about to
 *    grant face access should already know we cannot scan a third party,
 *    that nothing is stored, and that the session is destroyed on exit.
 *    Putting the trust posture after the biometric ask would be exactly
 *    backwards.
 */

import type {ReactNode} from "react";

type Props = {
  onBegin: () => void;
  onMockPreview: () => void;
  /** Disabled while the intel service is still coming up. */
  busy?: boolean;
  serviceReady?: boolean;
};

function Trust({label, children}: {label: string; children: ReactNode}) {
  return (
    <div>
      <strong>{label}</strong>
      <span>{children}</span>
    </div>
  );
}

export function MirrorLanding({onBegin, onMockPreview, busy, serviceReady = true}: Props) {
  return (
    <div className="stage" data-stage="landing">
      <div className="stage-inner landing">
        <div className="landing-mark">
          <i aria-hidden="true">M</i>
          <span>DDU / Mirror</span>
        </div>

        <h1>
          See what they&apos;d see.
        </h1>

        <p className="tagline">Start with yourself.</p>

        <p className="lede">
          The same intelligence engine an attacker would point at you, pointed
          inward instead. Verify that you are you, choose what to look for, and
          watch your exposure assemble itself &mdash; then take it apart.
        </p>

        <div className="landing-cta">
          <button
            className="btn-primary"
            disabled={busy || !serviceReady}
            onClick={onBegin}
            type="button"
          >
            {serviceReady ? "Verify and begin" : "Waiting for intelligence service…"}
          </button>
          <button className="btn-quiet" disabled={busy} onClick={onMockPreview} type="button">
            Preview with sample data
          </button>
        </div>

        <div className="landing-trust">
          <Trust label="Only you">
            There is no field to type someone else&apos;s name into. Every scan is
            asserted against an identity you proved you control.
          </Trust>
          <Trust label="Live proof">
            A face challenge shows a person is present now. A password only shows
            someone once had one.
          </Trust>
          <Trust label="Nothing kept">
            Findings live in memory for the session. Your face frame is matched,
            then destroyed &mdash; never stored.
          </Trust>
          <Trust label="You decide">
            The agent proposes; it never acts. Approve, edit, or reject every
            step, and reject any finding that isn&apos;t you.
          </Trust>
        </div>
      </div>
    </div>
  );
}
