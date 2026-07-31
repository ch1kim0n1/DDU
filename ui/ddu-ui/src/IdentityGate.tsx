/**
 * Identity gate — live face check or demo photo-ID upload.
 *
 * Wraps Engineer C's `LivenessChallenge` and the demo `IdDocumentVerify`
 * path. Face remains the stronger "person present now" argument; photo ID
 * is an alternate soft assurance with mock OCR (disclosed). Skipping either
 * downgrades to email-only without locking the user out.
 */

import {useState} from "react";

import {IdDocumentVerify} from "./IdDocumentVerify";
import {LivenessChallenge} from "./LivenessChallenge";

export type Assurance = "live_face" | "id_document" | "email_only";

type Path = "face" | "id";

type Props = {
  sessionId: string;
  onVerified: (assurance: Assurance) => void;
  onBack?: () => void;
};

export function IdentityGate({sessionId, onVerified, onBack}: Props) {
  const [path, setPath] = useState<Path>("face");
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
              Use a live face challenge, or upload a student ID / driver&apos;s
              license for the demo ID path. Camera video never leaves your
              device as a stream; ID images are session-scoped and wiped with
              the session.
            </p>
          </div>

          <div className="verify-path-tabs" role="tablist" aria-label="Verification method">
            <button
              aria-selected={path === "face"}
              className={path === "face" ? "is-on" : ""}
              onClick={() => {
                setPath("face");
                setFailed(false);
              }}
              role="tab"
              type="button"
            >
              Live face
            </button>
            <button
              aria-selected={path === "id"}
              className={path === "id" ? "is-on" : ""}
              onClick={() => {
                setPath("id");
                setFailed(false);
              }}
              role="tab"
              type="button"
            >
              Photo ID
            </button>
          </div>

          <div className="verify-body">
            <div>
              <div className="verify-frame">
                {path === "face" ? (
                  <LivenessChallenge
                    onFailed={() => setFailed(true)}
                    onPassed={() => onVerified("live_face")}
                    onSkipped={() => onVerified("email_only")}
                    sessionId={sessionId}
                  />
                ) : (
                  <IdDocumentVerify
                    onSkipped={() => onVerified("email_only")}
                    onVerified={() => onVerified("id_document")}
                    sessionId={sessionId}
                  />
                )}
              </div>
              {failed && path === "face" ? (
                <div className="verify-instruction" role="status">
                  <span className="dot" aria-hidden="true" />
                  Challenge didn&apos;t pass. Try again, switch to Photo ID, or
                  continue with email-only assurance.
                </div>
              ) : null}
            </div>

            <div className="verify-why">
              {path === "face" ? (
                <>
                  <div>
                    <strong>Why a face, not just a code</strong>
                    <p>
                      An emailed code proves someone had your inbox. If that inbox
                      is already compromised, the code proves nothing about who is
                      here. A live challenge does.
                    </p>
                  </div>
                  <div>
                    <strong>What we keep</strong>
                    <p>
                      Nothing durable. The face template is computed, matched
                      against your own verified avatars, and destroyed with the
                      session. There is no enrolment database.
                    </p>
                  </div>
                  <div>
                    <strong>If this doesn&apos;t work for you</strong>
                    <p>
                      Switch to Photo ID, or skip. Skipping keeps every feature
                      &mdash; it just labels this session{" "}
                      <em>email-only assurance</em>.
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <strong>Demo ID path</strong>
                    <p>
                      Upload a student ID or driver&apos;s license. Mirror runs
                      mock OCR (disclosed), vaults the fields, and labels the
                      session <em>ID verified</em>. This is not government KYC.
                    </p>
                  </div>
                  <div>
                    <strong>What we keep</strong>
                    <p>
                      Redacted findings in this session only. Wipe destroys the
                      upload metadata and OCR state with everything else.
                    </p>
                  </div>
                  <div>
                    <strong>What this is not</strong>
                    <p>
                      We do not match your face to the ID portrait in this path.
                      Prefer Live face when you want proof of presence.
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="stage-foot">
            <p className="note">
              Biometric or ID-image consent is requested above and logged. Texas
              CUBI, Illinois BIPA, and GDPR Art. 9 apply to biometric paths.
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
