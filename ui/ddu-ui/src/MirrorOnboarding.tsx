import {useEffect, useState, type FormEvent} from "react";

import {mirrorApi, type MirrorSession} from "./mirrorApi";

const personas = [
  ["employer", "Employer or recruiter"],
  ["stalker", "Stalker or abusive ex"],
  ["scammer", "Scammer or account thief"],
  ["state", "State-level actor"],
] as const;

export function MirrorOnboarding() {
  const [persona, setPersona] = useState("scammer");
  const [guess, setGuess] = useState("");
  const [email, setEmail] = useState("");
  const [adult, setAdult] = useState(false);
  const [challenge, setChallenge] = useState("");
  const [developmentCode, setDevelopmentCode] = useState("");
  const [code, setCode] = useState("");
  const [session, setSession] = useState<MirrorSession>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!seconds) return;
    const timer = window.setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [seconds]);

  async function start(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const result = await mirrorApi.start({email, adult_confirmed: adult, persona, guess_first: guess || undefined});
      setChallenge(result.challenge_id); setDevelopmentCode(result.development_code || "");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start verification."); } finally { setBusy(false); }
  }

  async function verify(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { setSession(await mirrorApi.verify(challenge, code)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Verification failed."); } finally { setBusy(false); }
  }

  async function chooseBiometric(accepted: boolean) {
    if (!session) return;
    setBusy(true); setError("");
    try {
      const next = await mirrorApi.biometric(session.session_id, accepted);
      setSession(next); setSeconds(next.biometric.destruction_countdown_seconds);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save consent."); } finally { setBusy(false); }
  }

  if (session) return (
    <main className="mirror-onboarding">
      <p className="eyebrow">DDU Mirror / verified session</p>
      <h1>You are scanning only what you control.</h1>
      <p className="lede">Verified identity: {session.verified_identity.email}. The scan cannot be pointed at someone else.</p>
      {!session.biometric.consented && <section className="mirror-card"><h2>Optional face check</h2><p>Face matching is limited to your verified accounts and uploads. You can skip this with no loss of core functionality.</p><div className="mirror-actions"><button disabled={busy} onClick={() => void chooseBiometric(true)}>I consent to face matching</button><button className="secondary" disabled={busy} onClick={() => void chooseBiometric(false)}>Skip face matching</button></div></section>}
      {session.biometric.consented && <section className="mirror-card"><h2>Face template deletion</h2><p>Your temporary face template will be destroyed in <strong>{seconds}s</strong>.</p></section>}
      <section className="mirror-card"><h2>Your consent is active</h2><p>Findings are ephemeral and disappear when you end this session.</p><button className="secondary" onClick={() => void mirrorApi.wipe(session.session_id).then(() => setSession(undefined))}>End and wipe session</button></section>
      {error && <p className="error">{error}</p>}
    </main>
  );

  if (challenge) return <main className="mirror-onboarding"><p className="eyebrow">DDU Mirror / verification</p><h1>Check your inbox.</h1><p className="lede">Enter the six-digit code to prove control of this identity. No scan starts before this step succeeds.</p><form className="mirror-card" onSubmit={verify}><label htmlFor="mirror-code">Verification code</label><input autoComplete="one-time-code" id="mirror-code" inputMode="numeric" maxLength={6} onChange={(event) => setCode(event.target.value)} value={code} />{developmentCode && <small>Local demo code: <code>{developmentCode}</code></small>}<button disabled={busy || code.length !== 6}>{busy ? "Verifying..." : "Verify identity"}</button></form>{error && <p className="error">{error}</p>}</main>;

  return <main className="mirror-onboarding"><p className="eyebrow">DDU Mirror / private exposure check</p><h1>Start with yourself. See what they'd see.</h1><p className="lede">DDU Mirror only scans identities you can verify. It cannot traverse to third parties.</p><form className="mirror-card" onSubmit={start}><fieldset><legend>Choose your threat model</legend><div className="persona-grid">{personas.map(([id, label]) => <label className={persona === id ? "persona selected" : "persona"} key={id}><input checked={persona === id} name="persona" onChange={() => setPersona(id)} type="radio" value={id} />{label}</label>)}</div></fieldset><label htmlFor="mirror-guess">What do you think is exposed? <small>(optional)</small></label><textarea id="mirror-guess" onChange={(event) => setGuess(event.target.value)} value={guess} /><label htmlFor="mirror-email">Email you control</label><input autoComplete="email" id="mirror-email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} /><label className="adult-check"><input checked={adult} onChange={(event) => setAdult(event.target.checked)} type="checkbox" /> I confirm that I am 18 or older.</label><button disabled={busy || !adult || !email}>{busy ? "Sending code..." : "Send verification code"}</button></form>{error && <p className="error">{error}</p>}</main>;
}
