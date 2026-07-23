package main

type ServiceVersion struct {
	Service        string `json:"service"`
	ServiceVersion string `json:"service_version"`
	Tool           string `json:"tool,omitempty"`
	ToolVersion    string `json:"tool_version,omitempty"`
	Model          string `json:"model,omitempty"`
	ModelVersion   string `json:"model_version,omitempty"`
	GitCommit      string `json:"git_commit,omitempty"`
	BuiltAt        string `json:"built_at,omitempty"`
}

type Provenance struct {
	InvestigationID   string            `json:"investigation_id,omitempty"`
	ProducedByService string            `json:"produced_by_service"`
	ProducerVersion   ServiceVersion    `json:"producer_version,omitempty"`
	Tool              string            `json:"tool,omitempty"`
	ToolVersion       string            `json:"tool_version,omitempty"`
	Model             string            `json:"model,omitempty"`
	ModelVersion      string            `json:"model_version,omitempty"`
	ProducedAt        string            `json:"produced_at,omitempty"`
	RunID             string            `json:"run_id,omitempty"`
	JobName           string            `json:"job_name,omitempty"`
	InputEvidenceIDs  []string          `json:"input_evidence_ids,omitempty"`
	ExtractionMethod  string            `json:"extraction_method,omitempty"`
	Parameters        map[string]string `json:"parameters,omitempty"`
}

type Observation struct {
	ID                 string            `json:"id"`
	InvestigationID    string            `json:"investigation_id"`
	EvidenceID         string            `json:"evidence_id"`
	Type               string            `json:"type"`
	Label              string            `json:"label"`
	DetectorConfidence float32           `json:"detector_confidence"`
	Attributes         map[string]string `json:"attributes"`
	Provenance         Provenance        `json:"provenance"`
	ObservedAt         string            `json:"observed_at"`
}

type DiscoverRequest struct {
	Username        string   `json:"username"`
	InvestigationID string   `json:"investigation_id"`
	Sites           []string `json:"sites,omitempty"`
}

type DiscoverResponse struct {
	Observations []Observation `json:"observations"`
}

type CandidateAccount struct {
	Platform   string `json:"platform"`
	ProfileURL string `json:"profile_url"`
	Username   string `json:"username"`
}
