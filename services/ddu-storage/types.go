package main

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
}

type EvidenceResponse struct {
	Evidence
	DownloadURL string `json:"download_url"`
}

type EvidenceList struct {
	Evidence []Evidence `json:"evidence"`
}
