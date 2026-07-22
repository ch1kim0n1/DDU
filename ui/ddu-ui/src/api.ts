const API_URL = (import.meta.env.VITE_DDU_API_URL || "http://localhost:8001").replace(
  /\/$/,
  "",
);

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

export interface WorkflowResult {
  evidence: Evidence;
  evidence_id: string;
  entities: Entity[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
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
