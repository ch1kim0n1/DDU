package main

type InvestigationMember struct {
	UserID  string `json:"user_id"`
	Role    string `json:"role"`
	AddedAt string `json:"added_at,omitempty"`
}

type Investigation struct {
	ID              string                `json:"id"`
	Name            string                `json:"name"`
	CreatedAt       string                `json:"created_at"`
	Members         []InvestigationMember `json:"members,omitempty"`
	RetentionPolicy RetentionPolicy       `json:"retention_policy,omitempty"`
}

type RetentionPolicy struct {
	RetentionDays  int    `json:"retention_days"`
	ExpiresAt      string `json:"expires_at,omitempty"`
	AutoDelete     bool   `json:"auto_delete"`
	ExportRequired bool   `json:"export_required"`
	Reason         string `json:"reason,omitempty"`
}

type ExportRequest struct {
	Format     string `json:"format"`     // json, csv, pdf
	IncludeRaw bool   `json:"include_raw"`
	Scope      string `json:"scope"`      // full, summary, evidence_only
}

type InvestigationList struct {
	Investigations []Investigation `json:"investigations"`
}

type Evidence struct {
	ID                string            `json:"id"`
	InvestigationID   string            `json:"investigation_id"`
	Type              string            `json:"type"`
	MimeType          string            `json:"mime_type"`
	SizeBytes         int64             `json:"size_bytes"`
	StorageURI        string            `json:"storage_uri"`
	OriginURI         string            `json:"origin_uri,omitempty"`
	AcquiredAt        string            `json:"acquired_at"`
	OriginalTimestamp string            `json:"original_timestamp,omitempty"`
	Metadata          map[string]string `json:"metadata"`
	AcquiredBy        string            `json:"acquired_by"`
	AcquisitionMethod string            `json:"acquisition_method"`
	ParentEvidenceIDs []string          `json:"parent_evidence_ids"`
	IsOriginal        bool              `json:"is_original"`
	DownloadURL       string            `json:"download_url,omitempty"`
}

type Observation struct {
	ID                 string            `json:"id"`
	InvestigationID    string            `json:"investigation_id"`
	EvidenceID         string            `json:"evidence_id"`
	Type               string            `json:"type"`
	Label              string            `json:"label"`
	DetectorConfidence float64           `json:"detector_confidence"`
	Attributes         map[string]string `json:"attributes"`
	Provenance         map[string]any    `json:"provenance"`
	ObservedAt         string            `json:"observed_at"`
	BBox               map[string]any    `json:"bbox,omitempty"`
	Geo                map[string]any    `json:"geo,omitempty"`
	Text               map[string]any    `json:"text,omitempty"`
}

type Entity struct {
	ID              string            `json:"id"`
	InvestigationID string            `json:"investigation_id"`
	Type            string            `json:"type"`
	Attributes      map[string]string `json:"attributes"`
	EvidenceIDs     []string          `json:"evidence_ids"`
	CreatedAt       string            `json:"created_at,omitempty"`
	UpdatedAt       string            `json:"updated_at,omitempty"`
	Provenance      map[string]any    `json:"provenance"`
}

type EntityList struct {
	Entities []Entity `json:"entities"`
}

type WorkflowResult struct {
	Evidence     Evidence      `json:"evidence"`
	EvidenceID   string        `json:"evidence_id"`
	Observations []Observation `json:"observations"`
	Entities     []Entity      `json:"entities"`
}

type RunsResponse struct {
	Runs  []map[string]any `json:"runs"`
	Count int              `json:"count"`
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

type Relationship struct {
	ID                      string         `json:"id"`
	InvestigationID         string         `json:"investigation_id"`
	SourceEntityID          string         `json:"source_entity_id"`
	TargetEntityID          string         `json:"target_entity_id"`
	RelationshipType        string         `json:"relationship_type"`
	VerificationState       string         `json:"verification_state"`
	Confidence              Confidence     `json:"confidence"`
	EvidenceIDs             []string       `json:"evidence_ids"`
	CandidateRelationshipID string         `json:"candidate_relationship_id,omitempty"`
	Provenance              map[string]any `json:"provenance"`
	CreatedAt               string         `json:"created_at"`
	UpdatedAt               string         `json:"updated_at"`
}

type RelationshipList struct {
	Relationships []Relationship `json:"relationships"`
	NextPageToken string         `json:"next_page_token,omitempty"`
}

type CandidateRelationship struct {
	ID                string         `json:"id"`
	InvestigationID   string         `json:"investigation_id"`
	SourceEntityID    string         `json:"source_entity_id"`
	TargetEntityID    string         `json:"target_entity_id"`
	RelationshipType  string         `json:"relationship_type"`
	Confidence        Confidence     `json:"confidence"`
	Signal            string         `json:"signal,omitempty"`
	VerificationState string         `json:"verification_state"`
	EvidenceIDs       []string       `json:"evidence_ids"`
	Provenance        map[string]any `json:"provenance"`
	CreatedAt         string         `json:"created_at"`
}
