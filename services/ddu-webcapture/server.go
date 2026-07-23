package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
)

type storageClient interface {
	Ping(context.Context) error
	Store(
		context.Context,
		string, string, string,
		[]byte,
		map[string]string,
		string, string, string,
	) (Evidence, error)
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	storage     storageClient
	browsertrix *browsertrixAdapter
	lineage     lineageEmitter
	client      *http.Client
}

func newHandler(storage storageClient, lineage lineageEmitter, client *http.Client) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 60 * time.Second}
	}
	s := &server{storage: storage, browsertrix: newBrowsertrixAdapter(client), lineage: lineage, client: client}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/capture", s.capture)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.storage.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName,
			"dependencies": []map[string]any{{"name": "ddu-storage", "ok": false, "detail": err.Error()}},
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName,
		"dependencies": []map[string]any{{"name": "ddu-storage", "ok": true, "detail": "reachable"}},
	})
}

func (s *server) capture(w http.ResponseWriter, r *http.Request) {
	var request CaptureRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&request); err != nil {
		writeError(w, http.StatusBadRequest, "valid JSON body is required")
		return
	}
	if strings.TrimSpace(request.URL) == "" || strings.TrimSpace(request.InvestigationID) == "" {
		writeError(w, http.StatusBadRequest, "url and investigation_id are required")
		return
	}
	parsed, err := url.Parse(strings.TrimSpace(request.URL))
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		writeError(w, http.StatusBadRequest, "url must be an absolute HTTP or HTTPS URL")
		return
	}
	waitSeconds := request.WaitSeconds
	if waitSeconds <= 0 {
		waitSeconds = 10
	}
	runID := s.start(r.Context(), "capture", request.InvestigationID, request.URL)
	warcContent, filename, err := s.browsertrix.Capture(r.Context(), request.URL, waitSeconds)
	if err != nil {
		s.fail(r.Context(), runID, "capture", request.InvestigationID, request.URL)
		writeError(w, http.StatusBadGateway, "browsertrix capture failed")
		return
	}
	extractionMethod := "browsertrix"
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		extractionMethod = "development-stub"
	}
	metadata := map[string]string{
		"source_url":   request.URL,
		"wait_seconds": strconv.Itoa(waitSeconds),
	}
	evidence, err := s.storage.Store(
		r.Context(), request.InvestigationID, filename, "application/warc+gzip", warcContent,
		metadata, request.URL, extractionMethod, "",
	)
	if err != nil {
		s.fail(r.Context(), runID, "capture", request.InvestigationID, request.URL)
		writeError(w, http.StatusBadGateway, "storage service rejected WARC content")
		return
	}
	evidence.Type = "EVIDENCE_TYPE_WEB_SNAPSHOT"
	s.complete(r.Context(), runID, "capture", request.InvestigationID, request.URL)
	writeJSON(w, http.StatusCreated, CaptureResponse{Evidence: evidence})
}

func (s *server) start(ctx context.Context, job, investigationID, input string) string {
	runID := lineageemitter.NewRunID()
	event := lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	}
	if input != "" {
		event.Inputs = []lineageemitter.Input{{Namespace: investigationID, Name: input, Type: "DDU.SOURCE"}}
	}
	s.emit(ctx, event)
	return runID
}

func (s *server) complete(ctx context.Context, runID, job, investigationID, input string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	})
}

func (s *server) fail(ctx context.Context, runID, job, investigationID, input string) {
	event := lineageemitter.Event{
		EventType: "FAIL", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	}
	if input != "" {
		event.Inputs = []lineageemitter.Input{{Namespace: investigationID, Name: input, Type: "DDU.SOURCE"}}
	}
	s.emit(ctx, event)
}

func (s *server) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func investigationFacet(investigationID string) map[string]string {
	value, _ := json.Marshal(map[string]string{"investigation_id": investigationID})
	return map[string]string{"dduInvestigation": string(value)}
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
