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

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const token = identityToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      ...(token ? {Authorization: `Bearer ${token}`} : {}),
    },
    body: form,
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

export type VisionDemoAsset = {
  sha256: string;
  slug?: string;
  filename?: string;
  label?: string;
  description?: string;
  platform?: string | null;
  has_objects?: boolean;
  has_geo?: boolean;
  face_boxes?: number;
};

export type VisionAnalyzeResult = {
  session_id: string;
  sha256: string;
  cache_hit: boolean;
  elapsed_ms: number;
  within_two_seconds: boolean;
  exif: {has_gps: boolean; has_device: boolean; datetime_original?: string | null};
  disclosures: string[];
  redaction_preview: {face_count: number; advice: string; boxes?: unknown[]};
  accepted: SessionSnapshot["findings"];
  score: SessionSnapshot["score"];
  snapshot: SessionSnapshot;
};

export const mirrorApi = {
  health: () => request<{state: string; service: string}>("/healthz"),

  createSession: (
    sessionId: string,
    persona = "scammer",
    seedMockFindings = true,
    emails: string[] = ["demo@ddu-mirror.local"],
    handles: string[] = ["demo_operator"],
    accountUrls: string[] = [],
  ) =>
    request<{session_id: string; snapshot: SessionSnapshot}>("/intel/session", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        emails,
        handles,
        account_urls: accountUrls,
        persona,
        seed_mock_findings: seedMockFindings,
      }),
    }),

  snapshot: (sessionId: string) =>
    request<SessionSnapshot>(`/intel/session/${encodeURIComponent(sessionId)}`),

  plan: (sessionId: string, state = "TX", county = "Travis") =>
    request<{proposals: SessionSnapshot["pending_proposals"]}>("/intel/scan/plan", {
      method: "POST",
      body: JSON.stringify({session_id: sessionId, state, county}),
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

  visionDemos: () =>
    request<{count: number; assets: VisionDemoAsset[]; note: string}>("/intel/vision/demos"),

  fetchDemoFile: async (slug: string) => {
    const response = await fetch(
      `${BASE_URL}/intel/vision/demos/${encodeURIComponent(slug)}`,
    );
    if (!response.ok) throw new Error(`Demo asset ${slug} unavailable`);
    const blob = await response.blob();
    return new File([blob], `${slug}.jpg`, {type: "image/jpeg"});
  },

  visionAnalyze: (sessionId: string, file: File, platform = "upload") => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("platform", platform);
    form.append("file", file);
    return requestForm<VisionAnalyzeResult>("/intel/vision/analyze", form);
  },

  livenessStart: (sessionId: string, challenge?: string) =>
    request<{
      challenge_id: string;
      challenge: string;
      instructions: string;
      privacy: string;
    }>("/intel/vision/liveness/start", {
      method: "POST",
      body: JSON.stringify({session_id: sessionId, challenge}),
    }),

  livenessComplete: (
    sessionId: string,
    challengeId: string,
    clientPassed: boolean,
    frame?: Blob | null,
  ) => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("challenge_id", challengeId);
    form.append("client_passed", clientPassed ? "true" : "false");
    if (frame) form.append("file", frame, "liveness.jpg");
    return requestForm<{
      passed: boolean;
      skipped: boolean;
      has_frame: boolean;
      template_ttl_seconds_remaining: number | null;
    }>("/intel/vision/liveness/complete", form);
  },

  livenessSkip: (sessionId: string) =>
    request<{skipped: boolean; dangling_state: boolean; corpus_cleared: number}>(
      "/intel/vision/liveness/skip",
      {
        method: "POST",
        body: JSON.stringify({session_id: sessionId}),
      },
    ),
};

export function websocketURL(sessionId: string) {
  const url = new URL(BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/intel/ws/${encodeURIComponent(sessionId)}`;
  return url.toString();
}
