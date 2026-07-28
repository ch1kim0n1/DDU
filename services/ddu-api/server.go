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

	dduhttpclient "github.com/ddu/ddu-httpclient"
	lineageemitter "github.com/ddu/ddu-lineage-emitter"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

const maxImageRequestBytes = 257 << 20

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type apiServer struct {
	downstream *downstreamClient
	lineage    lineageEmitter
	store      *investigationStore
	plugins    map[string]Plugin
	pluginMtx  sync.RWMutex
}

type Plugin struct {
	ID          string            `json:"id"`
	Name        string            `json:"name"`
	Version     string            `json:"version"`
	Description string            `json:"description"`
	Phase       int               `json:"phase"`
	Endpoint    string            `json:"endpoint"`
	HealthzURL  string            `json:"healthz_url"`
	VersionzURL string            `json:"versionz_url"`
	Metadata    map[string]string `json:"metadata"`
	RegisteredAt string           `json:"registered_at"`
}

func newHandler(urls serviceURLs, client *dduhttpclient.Client, lineage lineageEmitter) http.Handler {
	if client == nil {
		client = dduhttpclient.NewClient(dduhttpclient.Config{Timeout: 5 * time.Minute})
	}
	s := &apiServer{
		downstream: &downstreamClient{urls: urls, client: client},
		lineage:    lineage,
		store:      newInvestigationStore(urls.GraphStore, client),
		plugins:    make(map[string]Plugin),
	}
	router := chi.NewRouter()
	router.Use(corsMiddleware)
	router.Use(s.rbacMiddleware)
	router.Get("/healthz", s.healthz)
	router.Get("/versionz", versionzHandler)
	router.Get("/", rootHandler)
	router.Post("/v1/auth/dev-token", s.issueDevToken)
	router.Post("/v1/investigations", s.createInvestigation)
	router.Get("/v1/investigations", s.listInvestigations)
	router.Get("/v1/investigations/{id}", s.getInvestigation)
	router.Post("/v1/investigations/{id}/images", s.processImage)
	router.Post("/v1/investigations/{id}/usernames", s.processUsername)
	router.Post("/v1/investigations/{id}/urls", s.processURL)
	router.Post("/v1/investigations/{id}/resolve", s.resolveInvestigation)
	router.Post("/v1/investigations/{id}/contradict", s.contradictInvestigation)
	router.Get("/v1/investigations/{id}/timeline", s.timeline)
	router.Post("/v1/investigations/{id}/snapshots", s.createSnapshot)
	router.Get("/v1/investigations/{id}/snapshots", s.listSnapshots)
	router.Post("/v1/investigations/{id}/reports", s.generateReport)
	router.Get("/v1/investigations/{id}/replay", s.replayInvestigation)
	router.Post("/v1/investigations/{id}/agent", s.runAgent)
	router.Get("/v1/investigations/{id}/members", s.manageMembers)
	router.Post("/v1/investigations/{id}/members", s.manageMembers)
	router.Patch("/v1/investigations/{id}/relationships/{relationshipID}/verification", s.verifyRelationship)
	router.Get("/v1/investigations/{id}/entities", s.listEntities)
	router.Get("/v1/investigations/{id}/retention-policy", s.getRetentionPolicy)
	router.Post("/v1/investigations/{id}/retention-policy", s.setRetentionPolicy)
	router.Post("/v1/investigations/{id}/export", s.exportInvestigation)
	router.Delete("/v1/investigations/{id}", s.deleteInvestigation)
	router.Get("/v1/investigations/{id}/observations", s.listObservations)
	router.Get("/v1/investigations/{id}/lineage", s.listLineage)
	router.Get("/v1/investigations/{id}/evidence", s.listEvidence)
	router.Get("/v1/investigations/{id}/evidence/{evidenceID}", s.getEvidence)
	router.Get("/v1/investigations/{id}/relationships", s.listRelationships)
	router.Get("/v1/plugins", s.listPlugins)
	router.Post("/v1/plugins", s.registerPlugin)
	router.Delete("/v1/plugins/{id}", s.deregisterPlugin)
	router.Get("/v1/ontology/types", s.listOntologyTypes)
	router.Post("/v1/investigations/{id}/ontology/types", s.createOntologyType)
	router.Get("/v1/intel/capabilities", s.intelCapabilities)
	router.Post("/v1/investigations/{id}/intel/location/current", s.intelProxy("location/current", "/v1/location/current"))
	router.Post("/v1/investigations/{id}/intel/household", s.intelProxy("household", "/v1/household"))
	router.Post("/v1/investigations/{id}/intel/property", s.intelProxy("property", "/v1/property"))
	router.Post("/v1/investigations/{id}/intel/identity/resolve", s.intelProxy("identity/resolve", "/v1/identity/resolve"))
	router.Post("/v1/investigations/{id}/intel/pattern-of-life", s.intelProxy("pattern-of-life", "/v1/pattern-of-life"))
	router.Post("/v1/investigations/{id}/intel/temporal/diff", s.intelProxy("temporal/diff", "/v1/temporal/diff"))
	router.Post("/v1/investigations/{id}/intel/social-circle", s.intelProxy("social-circle", "/v1/social-circle"))
	router.Post("/v1/investigations/{id}/intel/location/history", s.intelProxy("location/history", "/v1/location/history"))
	router.Post("/v1/investigations/{id}/intel/aliases", s.intelProxy("aliases", "/v1/aliases"))
	router.Post("/v1/investigations/{id}/intel/records/fuse", s.intelProxy("records/fuse", "/v1/records/fuse"))
	router.Post("/v1/investigations/{id}/intel/relationship/strength", s.intelProxy("relationship/strength", "/v1/relationship/strength"))
	router.Post("/v1/investigations/{id}/intel/life-events", s.intelProxy("life-events", "/v1/life-events"))
	router.Post("/v1/investigations/{id}/intel/employment", s.intelProxy("employment", "/v1/employment"))
	router.Post("/v1/investigations/{id}/intel/assets", s.intelProxy("assets", "/v1/assets"))
	router.Post("/v1/investigations/{id}/intel/web-history", s.intelProxy("web-history", "/v1/web-history"))
	router.Post("/v1/investigations/{id}/intel/location/fuse", s.intelProxy("location/fuse", "/v1/location/fuse"))
	router.Get("/v1/investigations/{id}/intel/scene/3d", s.intelGET("scene/3d", "/v1/scene/3d"))
	router.Get("/v1/investigations/{id}/intel/playback", s.intelGET("playback", "/v1/playback"))
	return router
}

func (s *apiServer) healthz(w http.ResponseWriter, r *http.Request) {
	required := map[string]string{
		"ddu-ingest":      s.downstream.urls.Ingest,
		"ddu-vision":      s.downstream.urls.Vision,
		"ddu-ocr":         s.downstream.urls.OCR,
		"ddu-geo":         s.downstream.urls.Geo,
		"ddu-graph-store": s.downstream.urls.GraphStore,
		"ddu-lineage":     s.downstream.urls.Lineage,
		"ddu-storage":     s.downstream.urls.Storage,
	}
	optional := map[string]string{
		"ddu-discovery":  s.downstream.urls.Discovery,
		"ddu-osint":      s.downstream.urls.OSINT,
		"ddu-collector":  s.downstream.urls.Collector,
		"ddu-webcapture": s.downstream.urls.Webcapture,
		"ddu-resolution": s.downstream.urls.Resolution,
		"ddu-agent":      s.downstream.urls.Agent,
		"ddu-face":       s.downstream.urls.Face,
		"ddu-audio":      s.downstream.urls.Audio,
		"ddu-temporal":   s.downstream.urls.Temporal,
		"ddu-vector":     s.downstream.urls.Vector,
		"ddu-intel":      s.downstream.urls.Intel,
	}
	dependencies := map[string]string{}
	for name, baseURL := range required {
		dependencies[name] = baseURL
	}
	for name, baseURL := range optional {
		dependencies[name] = baseURL
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
	requiredHealthy := true
	optionalHealthy := true
	for range dependencies {
		item := <-results
		status := map[string]any{"name": item.name, "ok": item.err == nil}
		if item.err != nil {
			status["detail"] = item.err.Error()
			if _, isRequired := required[item.name]; isRequired {
				requiredHealthy = false
			} else {
				optionalHealthy = false
			}
		} else {
			status["detail"] = "reachable"
		}
		statuses = append(statuses, status)
	}
	sort.Slice(statuses, func(i, j int) bool {
		return statuses[i]["name"].(string) < statuses[j]["name"].(string)
	})
	if !requiredHealthy {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName, "dependencies": statuses,
		})
		return
	}
	state := "HEALTHY"
	if !optionalHealthy {
		state = "DEGRADED"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": state, "service": serviceName, "dependencies": statuses,
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
	id := identityFromContext(r.Context())
	investigation := Investigation{
		ID:        uuid.NewString(),
		Name:      strings.TrimSpace(input.Name),
		CreatedAt: time.Now().UTC().Format(time.RFC3339Nano),
		Members: []InvestigationMember{{
			UserID:  id.UserID,
			Role:    id.Role,
			AddedAt: time.Now().UTC().Format(time.RFC3339Nano),
		}},
	}
	runID := s.start(r.Context(), "create-investigation", investigation.ID, nil)
	// Persist to Neo4j via graph-store; cache remains even if downstream is degraded.
	_ = s.store.Put(r.Context(), investigation)
	s.audit(r, "CREATE_INVESTIGATION", "Investigation", investigation.ID, http.StatusCreated)
	s.complete(r.Context(), runID, "create-investigation", investigation.ID, []lineageemitter.Output{{
		Namespace: investigation.ID, Name: investigation.ID, Type: "DDU.INVESTIGATION",
	}})
	writeJSON(w, http.StatusCreated, investigation)
}

func (s *apiServer) listInvestigations(w http.ResponseWriter, r *http.Request) {
	investigations := s.store.List(r.Context())
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

	observations, entities, processErr := s.runPerception(r.Context(), investigationID, evidence.ID)
	if processErr != nil {
		s.fail(r.Context(), runID, "process-image", investigationID)
		writeError(w, http.StatusBadGateway, "perception failed: "+processErr.Error())
		return
	}
	sort.Slice(observations, func(i, j int) bool {
		return observations[i].ID < observations[j].ID
	})
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

func (s *apiServer) listRelationships(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	relationships, err := s.downstream.listRelationships(r.Context(), investigationID)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	runID := s.start(r.Context(), "list-relationships", investigationID, nil)
	s.complete(r.Context(), runID, "list-relationships", investigationID, nil)
	writeJSON(w, http.StatusOK, relationships)
}

func (s *apiServer) investigation(id string) (Investigation, bool) {
	return s.store.Get(context.Background(), id)
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
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-Investigation-Id, X-DDU-Role, X-DDU-Authorization-Purpose")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
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
