package main

type CreateCollectionRequest struct {
	Name            string `json:"name"`
	VectorSize      uint64 `json:"vector_size"`
	Distance        string `json:"distance"`
	InvestigationID string `json:"investigation_id,omitempty"`
}

type Point struct {
	ID      string         `json:"id"`
	Vector  []float32      `json:"vector"`
	Payload map[string]any `json:"payload"`
}

type UpsertRequest struct {
	Collection      string  `json:"collection"`
	Points          []Point `json:"points"`
	InvestigationID string  `json:"investigation_id,omitempty"`
}

type SearchRequest struct {
	Collection      string         `json:"collection"`
	Vector          []float32      `json:"vector"`
	Limit           uint64         `json:"limit,omitempty"`
	Filter          map[string]any `json:"filter,omitempty"`
	WithVectors     bool           `json:"with_vectors,omitempty"`
	InvestigationID string         `json:"investigation_id,omitempty"`
}

type Match struct {
	ID      string         `json:"id"`
	Score   float32        `json:"score"`
	Payload map[string]any `json:"payload"`
	Vector  []float32      `json:"vector,omitempty"`
}

type SearchResponse struct {
	Matches []Match `json:"matches"`
}
