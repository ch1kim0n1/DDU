package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
)

type vectorRepository interface {
	Ping(context.Context) error
	CreateCollection(context.Context, string, uint64, string) error
	Upsert(context.Context, string, []Point) error
	Search(context.Context, SearchRequest) ([]Match, error)
	Close() error
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	repository vectorRepository
	lineage    lineageEmitter
}

func newHandler(repository vectorRepository, lineage lineageEmitter) http.Handler {
	s := &server{repository: repository, lineage: lineage}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/collections", s.createCollection)
	mux.HandleFunc("POST /v1/points/upsert", s.upsert)
	mux.HandleFunc("POST /v1/search", s.search)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.repository.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName,
			"dependencies": []map[string]any{{"name": "qdrant", "ok": false, "detail": err.Error()}},
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName,
		"dependencies": []map[string]any{{"name": "qdrant", "ok": true, "detail": "reachable"}},
	})
}

func (s *server) createCollection(w http.ResponseWriter, r *http.Request) {
	var request CreateCollectionRequest
	if err := decodeJSON(r.Body, &request); err != nil ||
		request.Name == "" || request.VectorSize == 0 || !validDistance(request.Distance) {
		writeError(w, http.StatusBadRequest, "name, vector_size, and valid distance are required")
		return
	}
	runID := s.start(r.Context(), "create-collection", request.InvestigationID)
	if err := s.repository.CreateCollection(r.Context(), request.Name, request.VectorSize, strings.ToUpper(request.Distance)); err != nil {
		s.fail(r.Context(), runID, "create-collection", request.InvestigationID)
		writeError(w, http.StatusBadGateway, "collection creation failed")
		return
	}
	s.complete(r.Context(), runID, "create-collection", request.InvestigationID, request.Name)
	writeJSON(w, http.StatusCreated, map[string]any{"created": true, "name": request.Name})
}

func (s *server) upsert(w http.ResponseWriter, r *http.Request) {
	var request UpsertRequest
	if err := decodeJSON(r.Body, &request); err != nil || request.Collection == "" || len(request.Points) == 0 {
		writeError(w, http.StatusBadRequest, "collection and points are required")
		return
	}
	for index := range request.Points {
		if request.Points[index].ID == "" || len(request.Points[index].Vector) == 0 {
			writeError(w, http.StatusBadRequest, "every point requires id and vector")
			return
		}
		if request.Points[index].Payload == nil {
			request.Points[index].Payload = map[string]any{}
		}
		if _, ok := request.Points[index].Payload["embedding_source"]; !ok {
			request.Points[index].Payload["embedding_source"] = "placeholder"
		}
	}
	runID := s.start(r.Context(), "upsert", request.InvestigationID)
	if err := s.repository.Upsert(r.Context(), request.Collection, request.Points); err != nil {
		s.fail(r.Context(), runID, "upsert", request.InvestigationID)
		writeError(w, http.StatusBadGateway, "point upsert failed")
		return
	}
	s.complete(r.Context(), runID, "upsert", request.InvestigationID, request.Collection)
	writeJSON(w, http.StatusOK, map[string]any{"upserted": len(request.Points)})
}

func (s *server) search(w http.ResponseWriter, r *http.Request) {
	var request SearchRequest
	if err := decodeJSON(r.Body, &request); err != nil || request.Collection == "" || len(request.Vector) == 0 {
		writeError(w, http.StatusBadRequest, "collection and vector are required")
		return
	}
	if request.Limit == 0 {
		request.Limit = 10
	}
	runID := s.start(r.Context(), "search", request.InvestigationID)
	matches, err := s.repository.Search(r.Context(), request)
	if err != nil {
		s.fail(r.Context(), runID, "search", request.InvestigationID)
		writeError(w, http.StatusBadGateway, "vector search failed")
		return
	}
	if matches == nil {
		matches = []Match{}
	}
	s.complete(r.Context(), runID, "search", request.InvestigationID, request.Collection)
	writeJSON(w, http.StatusOK, SearchResponse{Matches: matches})
}

func validDistance(value string) bool {
	switch strings.ToUpper(strings.TrimSpace(value)) {
	case "COSINE", "DOT", "EUCLID", "MANHATTAN":
		return true
	default:
		return false
	}
}

func decodeJSON(reader io.Reader, target any) error {
	return json.NewDecoder(io.LimitReader(reader, 4<<20)).Decode(target)
}

func (s *server) start(ctx context.Context, job, investigationID string) string {
	runID := lineageemitter.NewRunID()
	s.emit(ctx, lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	})
	return runID
}

func (s *server) complete(ctx context.Context, runID, job, investigationID, output string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":" + job,
		Outputs: []lineageemitter.Output{{
			Namespace: investigationID, Name: output, Type: "DDU.VECTOR",
		}},
		Facets: investigationFacet(investigationID),
	})
}

func (s *server) fail(ctx context.Context, runID, job, investigationID string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "FAIL", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	})
}

func (s *server) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func investigationFacet(investigationID string) map[string]string {
	if investigationID == "" {
		return nil
	}
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
