import {useState} from "react";

export interface OnboardingData {
  emails: string[];
  handles: string[];
  accountUrls: string[];
  persona: string;
  state: string;
  county: string;
  guess: string;
}

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
  const [localError, setLocalError] = useState("");

  const totalSteps = 4;
  const canProceed = step === 0
    ? emails.length > 0
    : step === 1
      ? Boolean(persona)
      : step === 2
        ? Boolean(state)
        : step === 3
          ? adult
          : false;

  function addEmail() {
    const clean = email.trim().toLowerCase();
    if (!clean || !clean.includes("@") || emails.includes(clean)) return;
    setEmails([...emails, clean]);
    setEmail("");
  }
  function removeEmail(value: string) {
    setEmails(emails.filter((e) => e !== value));
  }

  function addHandle() {
    const clean = handle.trim().replace(/^@/, "").toLowerCase();
    if (!clean || handles.includes(clean)) return;
    setHandles([...handles, clean]);
    setHandle("");
  }
  function removeHandle(value: string) {
    setHandles(handles.filter((h) => h !== value));
  }

  function addUrl() {
    const clean = accountUrl.trim();
    if (!clean || !clean.startsWith("http") || accountUrls.includes(clean)) return;
    setAccountUrls([...accountUrls, clean]);
    setAccountUrl("");
  }
  function removeUrl(value: string) {
    setAccountUrls(accountUrls.filter((u) => u !== value));
  }

  function next() {
    setLocalError("");
    if (step === 0 && emails.length === 0) {
      setLocalError("Add at least one email you control.");
      return;
    }
    if (step < totalSteps - 1) setStep(step + 1);
    else {
      onComplete({
        emails,
        handles,
        accountUrls,
        persona,
        state,
        county: county.trim() || "Travis",
        guess: guess.trim(),
      });
    }
  }

  function back() {
    setLocalError("");
    if (step > 0) setStep(step - 1);
    else onCancel();
  }

  return (
    <div className="wizard-overlay">
      <div className="wizard-card">
        <div className="wizard-header">
          <span className="wizard-brand">M</span>
          <div>
            <strong>DDU / MIRROR</strong>
            <small>Real discovery onboarding</small>
          </div>
          <button className="wizard-close" onClick={onCancel} type="button" aria-label="Cancel">
            X
          </button>
        </div>

        <div className="wizard-progress">
          {Array.from({length: totalSteps}, (_, i) => (
            <span key={i} className={`wizard-dot ${i === step ? "active" : ""} ${i < step ? "done" : ""}`} />
          ))}
        </div>

        <div className="wizard-body">
          {step === 0 && (
            <fieldset className="wizard-step">
              <legend>Step 1 - Your verified identity</legend>
              <p className="wizard-intro">
                Enter identifiers you control. DDU Mirror only scans what you
                can prove is yours. Nothing else.
              </p>

              <label className="wizard-field">
                <span>Email address</span>
                <div className="wizard-input-row">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
                    placeholder="you@example.com"
                  />
                  <button type="button" onClick={addEmail} disabled={!email.trim()}>Add</button>
                </div>
              </label>
              {emails.length > 0 && (
                <div className="wizard-chips">
                  {emails.map((value) => (
                    <span className="wizard-chip" key={value}>
                      {value}
                      <button type="button" onClick={() => removeEmail(value)}>x</button>
                    </span>
                  ))}
                </div>
              )}

              <label className="wizard-field">
                <span>Username / handle (optional)</span>
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
                      <button type="button" onClick={() => removeHandle(value)}>x</button>
                    </span>
                  ))}
                </div>
              )}

              <label className="wizard-field">
                <span>Profile URL (optional)</span>
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
                      <button type="button" onClick={() => removeUrl(value)}>x</button>
                    </span>
                  ))}
                </div>
              )}
            </fieldset>
          )}

          {step === 1 && (
            <fieldset className="wizard-step">
              <legend>Step 2 - Threat model</legend>
              <p className="wizard-intro">
                Who are you trying to stay safe from? This shapes how findings
                are weighted and which attack paths are prioritized.
              </p>
              <div className="wizard-personas">
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
              <legend>Step 3 - Context</legend>
              <p className="wizard-intro">
                Jurisdiction helps the records advisor tell you what is public
                where you live. The guess is optional and never leaves your
                session.
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
              <legend>Step 4 - Consent</legend>
              <p className="wizard-intro">
                Review what happens next before you start.
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
                    checked={adult}
                    onChange={(e) => setAdult(e.target.checked)}
                  />
                  I confirm that I am 18 or older and I consent to scanning my own public footprint.
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
