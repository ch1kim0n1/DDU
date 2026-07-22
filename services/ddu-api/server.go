package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

const maxImageRequestBytes = 257 << 20

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type apiServer struct {
	downstream     *downstreamClient
	lineage        lineageEmitter
	mu             sync.RWMutex
	investigations map[string]Investigation
}

func newHandler(urls serviceURLs, client *http.Client, lineage lineageEmitter) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Minute}
	}
	s := &apiServer{
		downstream:     &downstreamClient{urls: urls, client: client},
		lineage:        lineage,
		investigations: map[string]Investigation{},
	}
	router := chi.NewRouter()
	router.Use(corsMiddleware)
	router.Get("/healthz", s.healthz)
	router.Get("/versionz", versionzHandler)
	router.Get("/", rootHandler)
	router.Post("/v1/investigations", s.createInvestigation)
	router.Get("/v1/investigations", s.listInvestigations)
	router.Get("/v1/investigations/{id}", s.getInvestigation)
	router.Post("/v1/investigations/{id}/images", s.processImage)
	router.Get("/v1/investigations/{id}/entities", s.listEntities)
	router.Get("/v1/investigations/{id}/observations", s.listObservations)
	router.Get("/v1/investigations/{id}/lineage", s.listLineage)
	router.Get("/v1/investigations/{id}/evidence", s.listEvidence)
	router.Get("/v1/investigations/{id}/evidence/{evidenceID}", s.getEvidence)
	return router
}

func (s *apiServer) healthz(w http.ResponseWriter, r *http.Request) {
	dependencies := map[string]string{
		"ddu-ingest":      s.downstream.urls.Ingest,
		"ddu-vision":      s.downstream.urls.Vision,
		"ddu-ocr":         s.downstream.urls.OCR,
		"ddu-geo":         s.downstream.urls.Geo,
		"ddu-graph-store": s.downstream.urls.GraphStore,
		"ddu-lineage":     s.downstream.urls.Lineage,
		"ddu-storage":     s.downstream.urls.Storage,
	}
	type result struct {
		name string
		err  error
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	results := make(chan result, len(dependencies))
	for name, baseURL := range dependencies {
		go func(name, baseURL string) {
			results <- result{name: name, err: s.downstream.health(ctx, baseURL)}
		}(name, baseURL)
	}
	statuses := make([]map[string]any, 0, len(dependencies))
	healthy := true
	for range dependencies {
		item := <-results
		status := map[string]any{"name": item.name, "ok": item.err == nil}
		if item.err != nil {
			healthy = false
			status["detail"] = item.err.Error()
		} else {
			status["detail"] = "reachable"
		}
		statuses = append(statuses, status)
	}
	sort.Slice(statuses, func(i, j int) bool {
		return statuses[i]["name"].(string) < statuses[j]["name"].(string)
	})
	if !healthy {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName, "dependencies": statuses,
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName, "dependencies": statuses,
	})
}

func (s *apiServer) createInvestigation(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Name string `json:"name"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		strings.TrimSpace(input.Name) == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	investigation := Investigation{
		ID:        uuid.NewString(),
		Name:      strings.TrimSpace(input.Name),
		CreatedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}
	runID := s.start(r.Context(), "create-investigation", investigation.ID, nil)
	s.mu.Lock()
	s.investigations[investigation.ID] = investigation
	s.mu.Unlock()
	s.complete(r.Context(), runID, "create-investigation", investigation.ID, []lineageemitter.Output{{
		Namespace: investigation.ID, Name: investigation.ID, Type: "DDU.INVESTIGATION",
	}})
	writeJSON(w, http.StatusCreated, investigation)
}

func (s *apiServer) listInvestigations(w http.ResponseWriter, _ *http.Request) {
	s.mu.RLock()
	investigations := make([]Investigation, 0, len(s.investigations))
	for _, investigation := range s.investigations {
		investigations = append(investigations, investigation)
	}
	s.mu.RUnlock()
	sort.Slice(investigations, func(i, j int) bool {
		return investigations[i].CreatedAt > investigations[j].CreatedAt
	})
	writeJSON(w, http.StatusOK, InvestigationList{Investigations: investigations})
}

func (s *apiServer) getInvestigation(w http.ResponseWriter, r *http.Request) {
	investigation, ok := s.investigation(chi.URLParam(r, "id"))
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	writeJSON(w, http.StatusOK, investigation)
}

func (s *apiServer) processImage(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
		writeError(w, http.StatusBadRequest, "multipart image upload is required")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxImageRequestBytes+1))
	if err != nil || len(body) > maxImageRequestBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "image request exceeds 257 MiB")
		return
	}
	runID := s.start(r.Context(), "process-image", investigationID, nil)
	evidence, err := s.downstream.ingestImage(
		r.Context(),
		investigationID,
		body,
		r.Header.Get("Content-Type"),
	)
	if err != nil {
		s.fail(r.Context(), runID, "process-image", investigationID)
		writeError(w, http.StatusBadGateway, "image ingest failed: "+err.Error())
		return
	}

	type inferenceResult struct {
		service      string
		observations []Observation
		err          error
	}
	request := map[string]any{
		"evidence_id": evidence.ID, "investigation_id": investigationID,
	}
	calls := []struct {
		service, baseURL, endpoint string
		payload                    map[string]any
	}{
		{"ddu-vision", s.downstream.urls.Vision, "/v1/detect", map[string]any{
			"evidence_id": evidence.ID, "investigation_id": investigationID,
			"prompts": []string{"person", "vehicle", "object"},
		}},
		{"ddu-ocr", s.downstream.urls.OCR, "/v1/ocr", request},
		{"ddu-geo", s.downstream.urls.Geo, "/v1/locate", map[string]any{
			"evidence_id": evidence.ID, "investigation_id": investigationID, "top_k": 5,
		}},
	}
	results := make(chan inferenceResult, len(calls))
	for _, call := range calls {
		go func(call struct {
			service, baseURL, endpoint string
			payload                    map[string]any
		}) {
			observations, invokeErr := s.downstream.invokeML(
				r.Context(), call.baseURL, call.endpoint, call.payload,
			)
			results <- inferenceResult{call.service, observations, invokeErr}
		}(call)
	}
	observations := make([]Observation, 0)
	for range calls {
		result := <-results
		if result.err != nil {
			s.fail(r.Context(), runID, "process-image", investigationID)
			writeError(w, http.StatusBadGateway, result.service+" failed: "+result.err.Error())
			return
		}
		observations = append(observations, result.observations...)
	}
	sort.Slice(observations, func(i, j int) bool {
		return observations[i].ID < observations[j].ID
	})

	entities := make([]Entity, 0, len(observations))
	for _, observation := range observations {
		entity := observationEntity(observation)
		created, createErr := s.downstream.createEntity(r.Context(), entity)
		if createErr != nil {
			s.fail(r.Context(), runID, "process-image", investigationID)
			writeError(w, http.StatusBadGateway, "observation persistence failed: "+createErr.Error())
			return
		}
		entities = append(entities, created)
	}
	outputs := []lineageemitter.Output{{
		Namespace: investigationID, Name: evidence.ID, Type: "DDU.EVIDENCE",
	}}
	for _, entity := range entities {
		outputs = append(outputs, lineageemitter.Output{
			Namespace: investigationID, Name: entity.ID, Type: "DDU.ENTITY",
		})
	}
	s.complete(r.Context(), runID, "process-image", investigationID, outputs)
	writeJSON(w, http.StatusCreated, WorkflowResult{
		Evidence: evidence, EvidenceID: evidence.ID,
		Observations: observations, Entities: entities,
	})
}

func (s *apiServer) listEntities(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	entities, err := s.downstream.listEntities(
		r.Context(), investigationID, r.URL.Query().Get("type"),
	)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, entities)
}

func (s *apiServer) listObservations(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	entities, err := s.downstream.listEntities(
		r.Context(), investigationID, "ENTITY_TYPE_OBSERVATION",
	)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	evidenceID := r.URL.Query().Get("evidence_id")
	if evidenceID != "" {
		filtered := make([]Entity, 0)
		for _, entity := range entities.Entities {
			if entity.Attributes["evidence_id"] == evidenceID {
				filtered = append(filtered, entity)
			}
		}
		entities.Entities = filtered
	}
	writeJSON(w, http.StatusOK, entities)
}

func (s *apiServer) listLineage(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	runs, err := s.downstream.listRuns(r.Context(), investigationID)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, runs)
}

func (s *apiServer) listEvidence(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	evidence, err := s.downstream.listEvidence(r.Context(), investigationID)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"evidence": evidence})
}

func (s *apiServer) getEvidence(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	evidence, err := s.downstream.getEvidence(
		r.Context(), investigationID, chi.URLParam(r, "evidenceID"),
	)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, evidence)
}

func (s *apiServer) investigation(id string) (Investigation, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	investigation, ok := s.investigations[id]
	return investigation, ok
}

func observationEntity(observation Observation) Entity {
	attributes := map[string]string{
		"label":               observation.Label,
		"observation_type":    observation.Type,
		"detector_confidence": fmt.Sprintf("%.8f", observation.DetectorConfidence),
		"evidence_id":         observation.EvidenceID,
		"observed_at":         observation.ObservedAt,
		"epistemic_class":     "EPISTEMIC_CLASS_OBSERVATION",
	}
	for key, value := range observation.Attributes {
		attributes[key] = value
	}
	for key, value := range map[string]map[string]any{
		"bbox": observation.BBox, "geo": observation.Geo, "text": observation.Text,
	} {
		if len(value) > 0 {
			data, _ := json.Marshal(value)
			attributes[key] = string(data)
		}
	}
	payload, _ := json.Marshal(observation)
	attributes["observation"] = string(payload)
	return Entity{
		ID: observation.ID, InvestigationID: observation.InvestigationID,
		Type: "ENTITY_TYPE_OBSERVATION", Attributes: attributes,
		EvidenceIDs: []string{observation.EvidenceID}, Provenance: observation.Provenance,
	}
}

func (s *apiServer) start(
	ctx context.Context,
	job, investigationID string,
	inputs []lineageemitter.Input,
) string {
	runID := lineageemitter.NewRunID()
	s.emit(ctx, lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":" + job,
		Inputs: inputs, Facets: investigationFacet(investigationID),
	})
	return runID
}

func (s *apiServer) complete(
	ctx context.Context,
	runID, job, investigationID string,
	outputs []lineageemitter.Output,
) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":" + job,
		Outputs: outputs, Facets: investigationFacet(investigationID),
	})
}

func (s *apiServer) fail(ctx context.Context, runID, job, investigationID string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "FAIL", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	})
}

func (s *apiServer) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func investigationFacet(investigationID string) map[string]string {
	value, _ := json.Marshal(map[string]string{"investigation_id": investigationID})
	return map[string]string{"dduInvestigation": string(value)}
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-Investigation-Id")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
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
