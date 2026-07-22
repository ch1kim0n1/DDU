package main

type Investigation struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	CreatedAt string `json:"created_at"`
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
