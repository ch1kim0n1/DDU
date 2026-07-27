import type {
  SessionSnapshot,
  SimulationResult,
  VoiceTurnResult,
} from "./mirror-types";

const BASE_URL = (import.meta.env.VITE_MIRROR_API_URL || "http://localhost:8120").replace(
  /\/$/,
  "",
);

function identityToken() {
  return sessionStorage.getItem("ddu.identityToken") || "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = identityToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? {Authorization: `Bearer ${token}`} : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as {detail?: unknown};
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail || body);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Mirror API returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const mirrorApi = {
  health: () => request<{state: string; service: string}>("/healthz"),

  createSession: (
    sessionId: string,
    persona = "scammer",
    seedMockFindings = true,
  ) =>
    request<{session_id: string; snapshot: SessionSnapshot}>("/intel/session", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        emails: ["demo@ddu-mirror.local"],
        handles: ["demo_operator"],
        persona,
        seed_mock_findings: seedMockFindings,
      }),
    }),

  snapshot: (sessionId: string) =>
    request<SessionSnapshot>(`/intel/session/${encodeURIComponent(sessionId)}`),

  plan: (sessionId: string) =>
    request<{proposals: SessionSnapshot["pending_proposals"]}>("/intel/scan/plan", {
      method: "POST",
      body: JSON.stringify({session_id: sessionId, state: "TX", county: "Travis"}),
    }),

  approve: (sessionId: string, proposalId: string) =>
    request("/intel/scan/approve", {
      method: "POST",
      body: JSON.stringify({session_id: sessionId, proposal_id: proposalId}),
    }),

  rejectProposal: (sessionId: string, proposalId: string) =>
    request("/intel/scan/reject", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        proposal_id: proposalId,
        reason: "Operator declined this expansion.",
      }),
    }),

  rejectFinding: (sessionId: string, findingId: string) =>
    request<{snapshot: SessionSnapshot}>(`/intel/findings/reject`, {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        finding_id: findingId,
        reason: "That's not me",
      }),
    }),

  reveal: (
    sessionId: string,
    findingId: string,
    evidenceKey: string,
    revealToken: string,
  ) =>
    request<{value: string}>("/intel/findings/reveal", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        finding_id: findingId,
        evidence_key: evidenceKey,
        reveal_token: revealToken,
      }),
    }),

  simulate: (sessionId: string, fixedFindingIds: string[]) =>
    request<SimulationResult>("/intel/simulate", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        fixed_finding_ids: fixedFindingIds,
      }),
    }),

  setPersona: (sessionId: string, persona: string) =>
    request("/intel/persona", {
      method: "POST",
      body: JSON.stringify({session_id: sessionId, persona}),
    }),

  wipe: (sessionId: string) =>
    request<{
      destroyed: Record<string, number>;
      action_log_summary: Record<string, number>;
    }>(`/intel/session/${encodeURIComponent(sessionId)}`, {method: "DELETE"}),

  voiceTurn: (
    sessionId: string,
    input: {transcript?: string; audioBase64?: string; mimeType?: string; mode?: string},
  ) =>
    request<VoiceTurnResult>("/intel/voice/turn", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        transcript: input.transcript,
        audio_base64: input.audioBase64,
        mime_type: input.mimeType,
        mode: input.mode || "question",
      }),
    }),
};

export function websocketURL(sessionId: string) {
  const url = new URL(BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/intel/ws/${encodeURIComponent(sessionId)}`;
  return url.toString();
}
