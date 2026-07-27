const MIRROR_URL = (import.meta.env.VITE_DDU_MIRROR_URL || "http://localhost:8130").replace(/\/$/, "");

export interface MirrorSession {
  session_id: string;
  persona: string;
  verified_identity: {email: string; verified: boolean};
  biometric: {consented: boolean; destruction_countdown_seconds: number};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${MIRROR_URL}${path}`, {
    ...init,
    headers: {"Content-Type": "application/json", ...init?.headers},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {detail?: {explanation?: string}} | null;
    throw new Error(body?.detail?.explanation || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const mirrorApi = {
  start: (body: {email: string; adult_confirmed: boolean; persona: string; guess_first?: string}) =>
    request<{challenge_id: string; development_code?: string}>("/v1/onboarding/start", {method: "POST", body: JSON.stringify(body)}),
  verify: (challenge_id: string, code: string) =>
    request<MirrorSession>("/v1/onboarding/verify", {method: "POST", body: JSON.stringify({challenge_id, code})}),
  biometric: (session_id: string, accepted: boolean) =>
    request<MirrorSession>("/v1/consent/biometric", {method: "POST", body: JSON.stringify({session_id, accepted})}),
  wipe: (session_id: string) => request<{message: string}>(`/v1/sessions/${encodeURIComponent(session_id)}`, {method: "DELETE"}),
};
