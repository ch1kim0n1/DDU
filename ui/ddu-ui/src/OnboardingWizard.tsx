import {useEffect, useRef, useState} from "react";

import {track} from "./analytics";
import {useFocusTrap} from "./focusTrap";

export interface OnboardingData {
  emails: string[];
  handles: string[];
  accountUrls: string[];
  persona: string;
  state: string;
  county: string;
  guess: string;
}

const WIZARD_KEY = "ddu.wizardData";
const WIZARD_MAX_AGE_MS = 10 * 60 * 1000;

interface OnboardingWizardProps {
  onComplete: (data: OnboardingData) => void;
  onCancel: () => void;
  busy: boolean;
  error: string;
}

const PERSONAS = [
  {
    id: "scammer",
    label: "Account takeover",
    desc: "Someone trying to steal your accounts or impersonate you.",
  },
  {
    id: "stalker",
    label: "Personal safety",
    desc: "Someone who might physically locate or harass you.",
  },
  {
    id: "employer",
    label: "Employer screening",
    desc: "A recruiter or background checker profiling your public footprint.",
  },
  {
    id: "state",
    label: "State actor",
    desc: "A well-resourced adversary with access to public records and legal process.",
  },
];

const US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
  "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY",
];

export function OnboardingWizard({onComplete, onCancel, busy, error}: OnboardingWizardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useFocusTrap(cardRef, true, onCancel, closeRef);

  const [step, setStep] = useState(0);
  const [email, setEmail] = useState("");
  const [emails, setEmails] = useState<string[]>([]);
  const [handle, setHandle] = useState("");
  const [handles, setHandles] = useState<string[]>([]);
  const [accountUrl, setAccountUrl] = useState("");
  const [accountUrls, setAccountUrls] = useState<string[]>([]);
  const [persona, setPersona] = useState("scammer");
  const [state, setState] = useState("TX");
  const [county, setCounty] = useState("Travis");
  const [guess, setGuess] = useState("");
  const [adult, setAdult] = useState(false);
  const [legalAck, setLegalAck] = useState(false);
  const [localError, setLocalError] = useState("");
  const [hydrated, setHydrated] = useState(false);

  const totalSteps = 4;
  const stepLabels = [
    "Your verified identity",
    "Threat model",
    "Context",
    "Consent",
  ];

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(WIZARD_KEY);
      if (!raw) {
        setHydrated(true);
        return;
      }
      const saved = JSON.parse(raw) as {
        at: number;
        step: number;
        emails: string[];
        handles: string[];
        accountUrls: string[];
        persona: string;
        state: string;
        county: string;
        guess: string;
      };
      if (Date.now() - saved.at > WIZARD_MAX_AGE_MS) {
        sessionStorage.removeItem(WIZARD_KEY);
      } else {
        setStep(saved.step || 0);
        setEmails(saved.emails || []);
        setHandles(saved.handles || []);
        setAccountUrls(saved.accountUrls || []);
        setPersona(saved.persona || "scammer");
        setState(saved.state || "TX");
        setCounty(saved.county || "Travis");
        setGuess(saved.guess || "");
      }
    } catch {
      sessionStorage.removeItem(WIZARD_KEY);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    sessionStorage.setItem(
      WIZARD_KEY,
      JSON.stringify({
        at: Date.now(),
        step,
        emails,
        handles,
        accountUrls,
        persona,
        state,
        county,
        guess,
      }),
    );
    track("wizard_step", {step: step + 1});
  }, [hydrated, step, emails, handles, accountUrls, persona, state, county, guess]);
  const canProceed = step === 0
    ? emails.length > 0
    : step === 1
      ? Boolean(persona)
      : step === 2
        ? Boolean(state)
        : step === 3
          ? adult && legalAck
          : false;

  function addEmail() {
    const clean = email.trim().toLowerCase();
    const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean);
    if (!valid) {
      setLocalError("Enter a valid email address.");
      return;
    }
    if (emails.includes(clean)) return;
    setEmails([...emails, clean]);
    setEmail("");
    setLocalError("");
  }
  function removeEmail(value: string) {
    setEmails(emails.filter((e) => e !== value));
  }

  function addHandle() {
    const clean = handle.trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9_]+$/.test(clean)) {
      setLocalError("Handles may only use letters, numbers, and underscores.");
      return;
    }
    if (handles.includes(clean)) return;
    setHandles([...handles, clean]);
    setHandle("");
    setLocalError("");
  }
  function removeHandle(value: string) {
    setHandles(handles.filter((h) => h !== value));
  }

  function addUrl() {
    let clean = accountUrl.trim();
    if (clean && !/^https?:\/\//i.test(clean)) clean = `https://${clean}`;
    if (!/^https?:\/\/.+/i.test(clean)) {
      setLocalError("Profile URL must start with http:// or https://");
      return;
    }
    if (accountUrls.includes(clean)) return;
    setAccountUrls([...accountUrls, clean]);
    setAccountUrl("");
    setLocalError("");
  }
  function removeUrl(value: string) {
    setAccountUrls(accountUrls.filter((u) => u !== value));
  }

  function clearWizardStorage() {
    sessionStorage.removeItem(WIZARD_KEY);
  }

  function next() {
    setLocalError("");
    if (step === 0 && emails.length === 0) {
      setLocalError("Add at least one email you control.");
      return;
    }
    if (step < totalSteps - 1) setStep(step + 1);
    else {
      const cleanEmails = emails
        .map((value) => value.trim().toLowerCase())
        .filter((value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value));
      const cleanHandles = handles.map((value) =>
        value
          .trim()
          .replace(/^@/, "")
          .toLowerCase()
          .replace(/[^a-z0-9_]/g, ""),
      ).filter(Boolean);
      const cleanUrls: string[] = [];
      for (const raw of accountUrls) {
        let value = raw.trim();
        if (!value) continue;
        if (!/^https?:\/\//i.test(value)) value = `https://${value}`;
        try {
          cleanUrls.push(new URL(value).toString());
        } catch {
          /* drop invalid */
        }
      }
      const cleanGuess = guess
        .trim()
        .replace(/<[^>]*>/g, "")
        .slice(0, 500);
      clearWizardStorage();
      track("wizard_completed", {persona});
      onComplete({
        emails: cleanEmails,
        handles: cleanHandles,
        accountUrls: cleanUrls,
        persona,
        state,
        county: county.trim() || "Travis",
        guess: cleanGuess,
      });
    }
  }

  function back() {
    setLocalError("");
    if (step === totalSteps - 1) {
      // Keep data; user can review before starting.
      setLocalError("Going back will keep your data. You can review and change before starting.");
    }
    if (step > 0) setStep(step - 1);
    else {
      track("wizard_abandoned", {step: step + 1});
      clearWizardStorage();
      onCancel();
    }
  }

  return (
    <div className="wizard-overlay">
      <div
        ref={cardRef}
        className="wizard-card"
        role="dialog"
        aria-modal="true"
        aria-label="Onboarding wizard"
      >
        <div className="wizard-header">
          <span className="wizard-brand">M</span>
          <div>
            <strong>DDU / MIRROR</strong>
            <small>Real discovery onboarding</small>
          </div>
          <button
            ref={closeRef}
            className="wizard-close"
            onClick={onCancel}
            type="button"
            aria-label="Cancel"
          >
            X
          </button>
        </div>

        <div className="wizard-progress" role="list" aria-label="Onboarding progress">
          {Array.from({length: totalSteps}, (_, i) => (
            <span
              key={i}
              role="listitem"
              aria-current={i === step ? "step" : undefined}
              className={`wizard-dot ${i === step ? "active" : ""} ${i < step ? "done" : ""}`}
            />
          ))}
        </div>
        <p className="sr-only" aria-live="polite">
          Step {step + 1} of {totalSteps}: {stepLabels[step]}
        </p>

        <div className="wizard-body">
          {step === 0 && (
            <fieldset className="wizard-step">
              <legend className="wizard-legend">
                <span className="wizard-eyebrow">Step 1 of {totalSteps}</span>
                <span className="wizard-headline">Which accounts are yours?</span>
              </legend>
              <p className="wizard-intro" id="wizard-email-help">
                Mirror only scans what you can prove you control. There is no
                field here for anyone else&apos;s name.
              </p>

              {/* Email is the one required identifier, so it gets the screen to
                  itself. The optional ones stay hidden until it is banked —
                  three identical label/input/Add rows stacked at once read as
                  three unfinished tasks and buried the one that mattered. */}
              <label className="wizard-field wizard-field--hero">
                <span>Your email address</span>
                <div className="wizard-input-row">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
                    placeholder="you@example.com"
                    aria-describedby="wizard-email-help"
                    autoFocus
                  />
                  <button type="button" onClick={addEmail} disabled={!email.trim()}>
                    Add
                  </button>
                </div>
              </label>
              {emails.length > 0 && (
                <div className="wizard-chips">
                  {emails.map((value) => (
                    <span className="wizard-chip" key={value}>
                      {value}
                      <button type="button" onClick={() => removeEmail(value)} aria-label={`Remove ${value}`}>×</button>
                    </span>
                  ))}
                </div>
              )}

              {emails.length === 0 ? (
                <p className="wizard-hint">
                  Press Enter or Add to confirm it. You can add more than one.
                </p>
              ) : (
                <div className="wizard-optional">
                  <p className="wizard-optional-title">
                    Anything else they could find you by?
                    <em>Optional</em>
                  </p>

                  <label className="wizard-field">
                    <span>Username or handle</span>
                    <div className="wizard-input-row">
                      <input
                        type="text"
                        value={handle}
                        onChange={(e) => setHandle(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addHandle(); } }}
                        placeholder="@yourhandle"
                      />
                      <button type="button" onClick={addHandle} disabled={!handle.trim()}>Add</button>
                    </div>
                  </label>
                  {handles.length > 0 && (
                    <div className="wizard-chips">
                      {handles.map((value) => (
                        <span className="wizard-chip" key={value}>
                          @{value}
                          <button type="button" onClick={() => removeHandle(value)} aria-label={`Remove ${value}`}>×</button>
                        </span>
                      ))}
                    </div>
                  )}

                  <label className="wizard-field">
                    <span>Profile URL</span>
                    <div className="wizard-input-row">
                      <input
                        type="url"
                        value={accountUrl}
                        onChange={(e) => setAccountUrl(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addUrl(); } }}
                        placeholder="https://linkedin.com/in/you"
                      />
                      <button type="button" onClick={addUrl} disabled={!accountUrl.trim()}>Add</button>
                    </div>
                  </label>
                  {accountUrls.length > 0 && (
                    <div className="wizard-chips">
                      {accountUrls.map((value) => (
                        <span className="wizard-chip url" key={value}>
                          {value.replace(/^https?:\/\//, "").slice(0, 40)}
                          <button type="button" onClick={() => removeUrl(value)} aria-label={`Remove ${value}`}>×</button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </fieldset>
          )}

          {step === 1 && (
            <fieldset className="wizard-step">
              <legend className="wizard-legend">
                <span className="wizard-eyebrow">Step 2 of {totalSteps}</span>
                <span className="wizard-headline">Who are you worried about?</span>
              </legend>
              <p className="wizard-intro">
                This changes how findings are weighted and which chains get
                surfaced first. You can change it later.
              </p>
              <div className="wizard-personas" role="radiogroup" aria-label="Threat model persona">
                {PERSONAS.map((p) => (
                  <label
                    className={`wizard-persona ${persona === p.id ? "selected" : ""}`}
                    key={p.id}
                  >
                    <input
                      type="radio"
                      name="persona"
                      value={p.id}
                      checked={persona === p.id}
                      onChange={() => setPersona(p.id)}
                    />
                    <strong>{p.label}</strong>
                    <small>{p.desc}</small>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {step === 2 && (
            <fieldset className="wizard-step">
              <legend className="wizard-legend">
                <span className="wizard-eyebrow">Step 3 of {totalSteps}</span>
                <span className="wizard-headline">Where do you live?</span>
              </legend>
              <p className="wizard-intro">
                Records law is state by state, so this decides what the advisor
                can tell you is public. Nothing is looked up and no record is
                retrieved.
              </p>
              <div className="wizard-row">
                <label className="wizard-field">
                  <span>State</span>
                  <select value={state} onChange={(e) => setState(e.target.value)}>
                    {US_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="wizard-field">
                  <span>County</span>
                  <input
                    type="text"
                    value={county}
                    onChange={(e) => setCounty(e.target.value)}
                    placeholder="Travis"
                  />
                </label>
              </div>
              <label className="wizard-field">
                <span>What do you think is exposed? (optional)</span>
                <textarea
                  value={guess}
                  onChange={(e) => setGuess(e.target.value)}
                  placeholder="My home address, my employer, old forum posts..."
                  rows={3}
                />
              </label>
            </fieldset>
          )}

          {step === 3 && (
            <fieldset className="wizard-step">
              <legend className="wizard-legend">
                <span className="wizard-eyebrow">Step 4 of {totalSteps}</span>
                <span className="wizard-headline">Before we start</span>
              </legend>
              <p className="wizard-intro">
                Three things that stay true for the whole session.
              </p>
              <div className="wizard-consent">
                <div className="wizard-consent-item">
                  <strong>Ephemeral session</strong>
                  <span>All findings are destroyed when you end the session or close the tab.</span>
                </div>
                <div className="wizard-consent-item">
                  <strong>No third-party scanning</strong>
                  <span>Discovery only searches for identifiers you listed above. It cannot target someone else.</span>
                </div>
                <div className="wizard-consent-item">
                  <strong>Human-in-the-loop</strong>
                  <span>Every expansion requires your approval before it runs. Nothing happens automatically.</span>
                </div>
                <label className="wizard-adult">
                  <input
                    type="checkbox"
                    role="checkbox"
                    aria-checked={adult}
                    checked={adult}
                    onChange={(e) => setAdult(e.target.checked)}
                    aria-label="I confirm that I am 18 or older and I consent to scanning my own public footprint."
                  />
                  I confirm that I am 18 or older and I consent to scanning my own public footprint.
                </label>
                <label className="wizard-adult">
                  <input
                    type="checkbox"
                    role="checkbox"
                    aria-checked={legalAck}
                    checked={legalAck}
                    onChange={(e) => setLegalAck(e.target.checked)}
                    aria-label="I have read and agree to the Privacy Policy and Terms of Service"
                  />
                  I have read and agree to the{" "}
                  <a href="/privacy-policy.html" target="_blank" rel="noopener noreferrer">
                    Privacy Policy
                  </a>{" "}
                  and{" "}
                  <a href="/terms-of-service.html" target="_blank" rel="noopener noreferrer">
                    Terms of Service
                  </a>
                  .
                </label>
              </div>
            </fieldset>
          )}
        </div>

        {(localError || error) && (
          <p className="wizard-error">{localError || error}</p>
        )}

        <div className="wizard-actions">
          <button className="wizard-back" type="button" onClick={back} disabled={busy}>
            {step === 0 ? "Cancel" : "Back"}
          </button>
          <button
            className="wizard-next"
            type="button"
            onClick={next}
            disabled={!canProceed || busy}
          >
            {busy
              ? "Starting session..."
              : step === totalSteps - 1
                ? "Start real scan"
                : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
