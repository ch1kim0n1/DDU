const API_URL = (import.meta.env.VITE_DDU_API_URL || "http://localhost:8001").replace(
  /\/$/,
  "",
);

const ROLE_KEY = "ddu.role";
const TOKEN_KEY = "ddu.access_token";

export function getRole() {
  return localStorage.getItem(ROLE_KEY) || "analyst";
}

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export async function setRole(role: string) {
  localStorage.setItem(ROLE_KEY, role);
  try {
    const response = await fetch(`${API_URL}/v1/auth/dev-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "ui-user", role }),
    });
    if (response.ok) {
      const body = (await response.json()) as { access_token?: string };
      if (body.access_token) {
        localStorage.setItem(TOKEN_KEY, body.access_token);
      }
    }
  } catch {
    // AUTH_MODE=dev still accepts X-DDU-Role when token mint is unavailable.
  }
}

export interface Investigation {
  id: string;
  name: string;
  created_at: string;
}

export interface Evidence {
  id: string;
  investigation_id: string;
  type: string;
  mime_type: string;
  size_bytes: number;
  storage_uri: string;
  acquired_at: string;
  metadata: Record<string, string>;
  acquisition_method: string;
  download_url?: string;
}

export interface Entity {
  id: string;
  investigation_id: string;
  type: string;
  attributes: Record<string, string>;
  evidence_ids: string[];
  created_at: string;
  provenance: Record<string, unknown>;
}

export interface RunSummary {
  run_id: string;
  event_type: string;
  event_time: string;
  job_name: string;
}

export interface Relationship {
  id: string;
  investigation_id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  verification_state?: string;
  confidence?: number | {value?: number};
  attributes?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  created_at?: string;
}

export interface WorkflowResult {
  evidence: Evidence;
  evidence_id: string;
  entities: Entity[];
}

export interface TimelineEvent {
  id?: string;
  timestamp?: string;
  label?: string;
  type?: string;
  entity_id?: string;
  evidence_id?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("X-DDU-Role")) {
    headers.set("X-DDU-Role", getRole());
  }
  const token = getAccessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_URL}${path}`, {...init, headers});
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listInvestigations: async () =>
    (await request<{investigations: Investigation[]}>("/v1/investigations"))
      .investigations,

  createInvestigation: (name: string) =>
    request<Investigation>("/v1/investigations", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name}),
    }),

  getInvestigation: (id: string) =>
    request<Investigation>(`/v1/investigations/${encodeURIComponent(id)}`),

  uploadImage: (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<WorkflowResult>(
      `/v1/investigations/${encodeURIComponent(id)}/images`,
      {method: "POST", body},
    );
  },

  processUsername: (id: string, username: string) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/usernames`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username}),
    }),

  processURL: (id: string, url: string, mode = "auto") =>
    request(`/v1/investigations/${encodeURIComponent(id)}/urls`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url, mode, process: true}),
    }),

  resolve: (id: string) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({threshold: 0.5}),
    }),

  verifyRelationship: (id: string, relationshipId: string, state: string) =>
    request(
      `/v1/investigations/${encodeURIComponent(id)}/relationships/${encodeURIComponent(relationshipId)}/verification`,
      {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({verification_state: state}),
      },
    ),

  timeline: async (id: string) =>
    (
      await request<{events: TimelineEvent[]}>(
        `/v1/investigations/${encodeURIComponent(id)}/timeline`,
      )
    ).events || [],

  createSnapshot: (id: string, label: string) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/snapshots`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label}),
    }),

  generateReport: (id: string) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/reports`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: "{}",
    }),

  runAgent: (id: string, mode: string, body: Record<string, unknown> = {}) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/agent`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mode, ...body}),
    }),

  listOntologyTypes: (investigationId?: string) => {
    const query = investigationId
      ? `?investigation_id=${encodeURIComponent(investigationId)}`
      : "";
    return request<{entity_types: Array<{name: string; number: number; custom?: boolean}>; custom_types?: unknown[]}>(
      `/v1/ontology/types${query}`,
    );
  },

  createOntologyType: (
    id: string,
    body: {name: string; description?: string; parent_type?: string},
  ) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/ontology/types`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    }),

  intel: (
    id: string,
    featurePath: string,
    body: Record<string, unknown> = {},
  ) =>
    request(`/v1/investigations/${encodeURIComponent(id)}/intel/${featurePath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DDU-Authorization-Purpose": "authorized-investigation",
      },
      body: JSON.stringify({
        authorization_purpose: "authorized-investigation",
        subject: body.subject || "subject",
        ...body,
      }),
    }),

  intelScene: (id: string) =>
    request<{nodes: Array<{id: string; label?: string; type?: string; x: number; y: number; z: number; confidence?: number}>; edges: Array<{id: string; source: string; target: string; type?: string; confidence?: number}>}>(
      `/v1/investigations/${encodeURIComponent(id)}/intel/scene/3d`,
    ),

  intelPlayback: (id: string) =>
    request<{frames: Array<{frame: number; narrative?: string; entity_count?: number; relationship_count?: number}>}>(
      `/v1/investigations/${encodeURIComponent(id)}/intel/playback`,
    ),

  listEntities: async (id: string) =>
    (
      await request<{entities: Entity[]}>(
        `/v1/investigations/${encodeURIComponent(id)}/entities`,
      )
    ).entities,

  listObservations: async (id: string, evidenceId?: string) => {
    const query = evidenceId
      ? `?evidence_id=${encodeURIComponent(evidenceId)}`
      : "";
    return (
      await request<{entities: Entity[]}>(
        `/v1/investigations/${encodeURIComponent(id)}/observations${query}`,
      )
    ).entities;
  },

  listLineage: (id: string) =>
    request<{runs: RunSummary[]; count: number}>(
      `/v1/investigations/${encodeURIComponent(id)}/lineage`,
    ),

  listRelationships: (id: string) =>
    request<{relationships: Relationship[]}>(
      `/v1/investigations/${encodeURIComponent(id)}/relationships`,
    ).then((r) => r.relationships || []),

  listEvidence: async (id: string) =>
    (
      await request<{evidence: Evidence[]}>(
        `/v1/investigations/${encodeURIComponent(id)}/evidence`,
      )
    ).evidence,

  getEvidence: (id: string, evidenceId: string) =>
    request<Evidence>(
      `/v1/investigations/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
    ),
};
