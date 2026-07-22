package main

type RunSummary struct {
	RunID           string `json:"run_id"`
	InvestigationID string `json:"investigation_id"`
	EventType       string `json:"event_type"`
	EventTime       string `json:"event_time"`
	JobNamespace    string `json:"job_namespace"`
	JobName         string `json:"job_name"`
}

type RunsResponse struct {
	Runs  []RunSummary `json:"runs"`
	Count int          `json:"count"`
}
