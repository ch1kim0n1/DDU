export type VerificationState =
  | "confirmed"
  | "likely"
  | "hypothesis"
  | "contradicted"
  | "rejected";

export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface EvidenceItem {
  kind: "kv" | "text" | "image_ref" | "url" | "record";
  k: string;
  v: string;
  reveal_token?: string | null;
  redacted: boolean;
}

export interface Finding {
  contract_version: string;
  id: string;
  parent_id?: string | null;
  hop_depth: number;
  type: string;
  label: string;
  detail: string;
  verification_state: VerificationState;
  confidence: number;
  severity_base: number;
  severity: Severity;
  severity_score: number;
  reversible: boolean;
  remediation: {
    action: string;
    compensating?: string | null;
    effort: "low" | "medium" | "high";
    permanent_note?: string | null;
  };
  platform?: string | null;
  source: string;
  method: string;
  evidence: EvidenceItem[];
  attack_path_ids: string[];
  subject_ref: string;
  origin: "agent" | "human" | "system";
  human_note?: string | null;
  timestamp: string;
}

export interface AttackPath {
  id: string;
  finding_ids: string[];
  narrative: string;
  feasibility: number;
  terminal_impact: string;
}

export interface PlatformAttribution {
  platform: string;
  finding_count: number;
  weighted_severity: number;
  share: number;
  hardening_hint: string;
}

export interface ScoreBreakdown {
  score: number;
  band: "minimal" | "moderate" | "elevated" | "severe" | "critical";
  persona: string;
  contributing_findings: number;
  suppressed_findings: number;
  irreversible_share: number;
  top_drivers: string[];
  by_severity: Record<Severity, number>;
}

export interface Proposal {
  id: string;
  session_id: string;
  step: string;
  title: string;
  rationale: string;
  inputs: Record<string, unknown>;
  expected_findings: string;
  touches_external: string[];
  /** Fields this step accepts on an edit. The edit form renders exactly these. */
  editable_inputs?: string[];
  parent_finding_id?: string | null;
  hop_depth: number;
  status:
    | "awaiting_approval"
    | "approved"
    | "edited"
    | "rejected"
    | "cancelled"
    | "executed"
    | "failed";
}

export interface ActionLogEntry {
  seq: number;
  session_id: string;
  at: string;
  actor: "agent" | "human" | "system";
  action: string;
  subject: string;
  detail: string;
  metadata: Record<string, unknown>;
}

export interface SessionSnapshot {
  session_id: string;
  contract_version: string;
  persona: string;
  findings: Finding[];
  attack_paths: AttackPath[];
  attribution: PlatformAttribution[];
  score: ScoreBreakdown;
  pending_proposals: Proposal[];
  action_log_tail: ActionLogEntry[];
}

export interface SimulationResult {
  score_now: ScoreBreakdown;
  score_projected: ScoreBreakdown;
  refused: string[];
  refused_reason?: string | null;
}

export interface VoiceTurnResult {
  transcript: string;
  transcript_redacted: boolean;
  replacements: Record<string, number>;
  answer: string;
  audio_base64?: string | null;
  audio_mime?: string | null;
  stt_provider: "elevenlabs" | "text" | "none";
  tts_provider: "elevenlabs" | "browser" | "none";
  llm_provider: string;
  offline: boolean;
  grounded_finding_ids: string[];
}
