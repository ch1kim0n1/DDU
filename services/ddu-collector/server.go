package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
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
	storage   storageClient
	galleryDL *galleryDLAdapter
	lineage   lineageEmitter
	client    *http.Client
}

func newHandler(storage storageClient, lineage lineageEmitter, client *http.Client) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 60 * time.Second}
	}
	s := &server{storage: storage, galleryDL: newGalleryDLAdapter(), lineage: lineage, client: client}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/collect", s.collect)
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

func (s *server) collect(w http.ResponseWriter, r *http.Request) {
	var request CollectRequest
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
	runID := s.start(r.Context(), "collect", request.InvestigationID, request.URL)
	tempDir, err := os.MkdirTemp("", "ddu-collector-*")
	if err != nil {
		s.fail(r.Context(), runID, "collect", request.InvestigationID, request.URL)
		writeError(w, http.StatusInternalServerError, "failed to create temp directory")
		return
	}
	defer os.RemoveAll(tempDir)
	files, err := s.galleryDL.Download(r.Context(), tempDir, request.URL, request.Options)
	if err != nil {
		s.fail(r.Context(), runID, "collect", request.InvestigationID, request.URL)
		writeError(w, http.StatusBadGateway, "gallery-dl download failed")
		return
	}
	extractionMethod := "gallery-dl"
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		extractionMethod = "development-stub"
	}
	var evidenceList []Evidence
	for _, file := range files {
		content, err := os.ReadFile(file.Path)
		if err != nil {
			s.fail(r.Context(), runID, "collect", request.InvestigationID, request.URL)
			writeError(w, http.StatusInternalServerError, "failed to read downloaded file")
			return
		}
		metadata := map[string]string{
			"source_url": request.URL,
			"filename":   file.Filename,
		}
		evidence, err := s.storage.Store(
			r.Context(), request.InvestigationID, file.Filename, file.MimeType, content,
			metadata, request.URL, extractionMethod, "",
		)
		if err != nil {
			s.fail(r.Context(), runID, "collect", request.InvestigationID, request.URL)
			writeError(w, http.StatusBadGateway, "storage service rejected downloaded content")
			return
		}
		evidenceList = append(evidenceList, evidence)
	}
	if evidenceList == nil {
		evidenceList = []Evidence{}
	}
	s.complete(r.Context(), runID, "collect", request.InvestigationID, request.URL)
	writeJSON(w, http.StatusCreated, CollectResponse{Evidence: evidenceList})
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
