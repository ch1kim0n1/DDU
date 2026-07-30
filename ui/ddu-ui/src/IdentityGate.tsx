/**
 * Identity gate — the live face challenge, framed.
 *
 * Wraps Engineer C's `LivenessChallenge` (MediaPipe FaceMesh, entirely
 * in-browser) rather than reimplementing it. This component owns the
 * *argument* around the challenge, not the mechanics.
 *
 * Why face is the primary path here rather than email alone:
 *
 *   An email code proves someone once had access to an inbox. If that
 *   inbox is already compromised — the residual risk the project spec
 *   admits to out loud — a code proves nothing about who is sitting at
 *   the keyboard. A liveness challenge proves a person is present now.
 *   That is a strictly higher bar, and it is the bar that matters for a
 *   tool whose whole promise is "only you can point this at you."
 *
 * Why a fallback still exists:
 *
 *   Face recognition has documented, uneven error rates across
 *   demographics, so a hard biometric wall excludes some people from
 *   their own privacy tooling. Skipping therefore does not hide
 *   findings — it downgrades a visible assurance level, so the UI
 *   states what was actually proven instead of implying more. That
 *   keeps the security argument honest in both directions.
 */

import {useState} from "react";

import {LivenessChallenge} from "./LivenessChallenge";

export type Assurance = "live_face" | "email_only";

type Props = {
  sessionId: string;
  onVerified: (assurance: Assurance) => void;
  onBack?: () => void;
};

export function IdentityGate({sessionId, onVerified, onBack}: Props) {
  const [failed, setFailed] = useState(false);

  return (
    <div className="stage" data-stage="verify">
      <div className="stage-inner">
        <div className="stage-steps" aria-label="Progress">
          <span className="is-done">
            <b>1</b> Identity
          </span>
          <i aria-hidden="true" />
          <span className="is-current">
            <b>2</b> Live check
          </span>
          <i aria-hidden="true" />
          <span>
            <b>3</b> Scope
          </span>
          <i aria-hidden="true" />
          <span>
            <b>4</b> Scan
          </span>
        </div>

        <div className="stage-card">
          <div className="stage-head">
            <p className="eyebrow">Step 2 of 4</p>
            <h2>Prove it&apos;s you, right now</h2>
            <p>
              We&apos;ll ask you to blink or turn your head. The camera feed is
              processed in your browser and never uploaded as video &mdash; at most
              one verified still frame leaves your device, and it is destroyed
              after matching.
            </p>
          </div>

          <div className="verify-body">
            <div>
              <div className="verify-frame">
                <LivenessChallenge
                  onFailed={() => setFailed(true)}
                  onPassed={() => onVerified("live_face")}
                  onSkipped={() => onVerified("email_only")}
                  sessionId={sessionId}
                />
              </div>
              {failed ? (
                <div className="verify-instruction" role="status">
                  <span className="dot" aria-hidden="true" />
                  Challenge didn&apos;t pass. Try again, or continue with email-only
                  assurance.
                </div>
              ) : null}
            </div>

            <div className="verify-why">
              <div>
                <strong>Why a face, not just a code</strong>
                <p>
                  An emailed code proves someone had your inbox. If that inbox is
                  already compromised, the code proves nothing about who is here.
                  A live challenge does.
                </p>
              </div>
              <div>
                <strong>What we keep</strong>
                <p>
                  Nothing durable. The face template is computed, matched against
                  your own verified avatars, and destroyed with the session. There
                  is no enrolment database.
                </p>
              </div>
              <div>
                <strong>If this doesn&apos;t work for you</strong>
                <p>
                  Face recognition fails unevenly across people, so you are never
                  locked out. Skipping keeps every feature &mdash; it just labels this
                  session <em>email-only assurance</em> instead of <em>live</em>.
                </p>
              </div>
            </div>
          </div>

          <div className="stage-foot">
            <p className="note">
              Biometric consent is requested separately above, and logged. Texas
              CUBI, Illinois BIPA, and GDPR Art. 9 all require that.
            </p>
            {onBack ? (
              <button className="btn-quiet" onClick={onBack} type="button">
                Back
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
