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

type Confidence struct {
	Value                  float32            `json:"value"`
	SupportingSignals      []string           `json:"supporting_signals,omitempty"`
	ContradictingSignals   []string           `json:"contradicting_signals,omitempty"`
	IndependentSourceCount int32              `json:"independent_source_count,omitempty"`
	ComputedBy             string             `json:"computed_by,omitempty"`
	ComputedAt             string             `json:"computed_at,omitempty"`
	SignalWeights          map[string]float32 `json:"signal_weights,omitempty"`
}

type Entity struct {
	ID              string            `json:"id"`
	InvestigationID string            `json:"investigation_id"`
	Type            string            `json:"type"`
	Attributes      map[string]string `json:"attributes"`
	EvidenceIDs     []string          `json:"evidence_ids"`
	CreatedAt       string            `json:"created_at"`
	UpdatedAt       string            `json:"updated_at"`
	Provenance      Provenance        `json:"provenance"`
}

type EntityList struct {
	Entities      []Entity `json:"entities"`
	NextPageToken string   `json:"next_page_token,omitempty"`
}

type Relationship struct {
	ID                      string     `json:"id"`
	InvestigationID         string     `json:"investigation_id"`
	SourceEntityID          string     `json:"source_entity_id"`
	TargetEntityID          string     `json:"target_entity_id"`
	RelationshipType        string     `json:"relationship_type"`
	VerificationState       string     `json:"verification_state"`
	Confidence              Confidence `json:"confidence"`
	EvidenceIDs             []string   `json:"evidence_ids"`
	CandidateRelationshipID string     `json:"candidate_relationship_id,omitempty"`
	Provenance              Provenance `json:"provenance"`
	CreatedAt               string     `json:"created_at"`
	UpdatedAt               string     `json:"updated_at"`
}

type RelationshipList struct {
	Relationships []Relationship `json:"relationships"`
	NextPageToken string         `json:"next_page_token,omitempty"`
}

type QueryRequest struct {
	Cypher     string         `json:"cypher"`
	Parameters map[string]any `json:"parameters"`
}

type QueryResponse struct {
	Records []map[string]any `json:"records"`
}
