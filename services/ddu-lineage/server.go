package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

type lineageProxy struct {
	backendURL string
	client     *http.Client
	mu         sync.RWMutex
	runs       map[string]RunSummary
	order      []string
}

type openLineageEvent struct {
	EventType string `json:"eventType"`
	EventTime string `json:"eventTime"`
	Run       struct {
		RunID  string                     `json:"runId"`
		Facets map[string]json.RawMessage `json:"facets"`
	} `json:"run"`
	Job struct {
		Namespace string `json:"namespace"`
		Name      string `json:"name"`
	} `json:"job"`
}

func newHandler(backendURL string, client *http.Client) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	s := &lineageProxy{
		backendURL: strings.TrimRight(backendURL, "/"),
		client:     client,
		runs:       map[string]RunSummary{},
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/events", s.forwardEvent)
	mux.HandleFunc("POST /api/v1/lineage", s.forwardEvent)
	mux.HandleFunc("GET /v1/runs", s.listRuns)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *lineageProxy) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.backendURL+"/api/v1/namespaces", nil)
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, err.Error())
		return
	}
	resp, err := s.client.Do(req)
	if err != nil || resp.StatusCode >= http.StatusBadRequest {
		detail := "backend unavailable"
		if err != nil {
			detail = err.Error()
		}
		if resp != nil {
			resp.Body.Close()
		}
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName,
			"dependencies": []map[string]any{{"name": "marquez", "ok": false, "detail": detail}},
		})
		return
	}
	resp.Body.Close()
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName,
		"dependencies": []map[string]any{{"name": "marquez", "ok": true, "detail": "reachable"}},
	})
}

func (s *lineageProxy) forwardEvent(w http.ResponseWriter, r *http.Request) {
	data, err := io.ReadAll(io.LimitReader(r.Body, 4<<20))
	if err != nil {
		writeError(w, http.StatusBadRequest, "unable to read lineage event")
		return
	}
	var event openLineageEvent
	if err := json.Unmarshal(data, &event); err != nil || event.Run.RunID == "" || event.Job.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid OpenLineage event")
		return
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, s.backendURL+"/api/v1/lineage", bytes.NewReader(data))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "lineage request creation failed")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.client.Do(req)
	if err != nil {
		writeError(w, http.StatusBadGateway, "Marquez forwarding failed")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		writeJSON(w, http.StatusBadGateway, map[string]any{
			"error": "Marquez rejected lineage event", "detail": string(body),
		})
		return
	}
	s.record(event)
	writeJSON(w, http.StatusAccepted, map[string]any{
		"accepted": true,
		"run_id":   event.Run.RunID,
	})
}

func (s *lineageProxy) listRuns(w http.ResponseWriter, r *http.Request) {
	investigationID := strings.TrimSpace(r.URL.Query().Get("investigation_id"))
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	runs := make([]RunSummary, 0)
	for _, runID := range s.order {
		run := s.runs[runID]
		if run.InvestigationID == investigationID {
			runs = append(runs, run)
		}
	}
	writeJSON(w, http.StatusOK, RunsResponse{Runs: runs, Count: len(runs)})
}

func (s *lineageProxy) record(event openLineageEvent) {
	investigationID := ""
	if raw, ok := event.Run.Facets["dduInvestigation"]; ok {
		var facet struct {
			InvestigationID string `json:"investigation_id"`
		}
		if json.Unmarshal(raw, &facet) == nil {
			investigationID = facet.InvestigationID
		}
	}
	run := RunSummary{
		RunID:           event.Run.RunID,
		InvestigationID: investigationID,
		EventType:       event.EventType,
		EventTime:       event.EventTime,
		JobNamespace:    event.Job.Namespace,
		JobName:         event.Job.Name,
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.runs[run.RunID]; !exists {
		s.order = append(s.order, run.RunID)
	}
	s.runs[run.RunID] = run
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil && !errors.Is(err, context.Canceled) {
		return
	}
}
