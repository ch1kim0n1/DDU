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
	"github.com/google/uuid"
)

type graphRepository interface {
	Ping(context.Context) error
	CreateEntity(context.Context, Entity) (Entity, error)
	GetEntity(context.Context, string) (Entity, error)
	ListEntities(context.Context, string, string) ([]Entity, error)
	CreateRelationship(context.Context, Relationship) (Relationship, error)
	ListRelationships(context.Context, string) ([]Relationship, error)
	Query(context.Context, string, map[string]any) ([]map[string]any, error)
	Close(context.Context) error
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	repository graphRepository
	lineage    lineageEmitter
	now        func() time.Time
}

func newHandler(repository graphRepository, lineage lineageEmitter) http.Handler {
	s := &server{repository: repository, lineage: lineage, now: time.Now}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/entities", s.createEntity)
	mux.HandleFunc("GET /v1/entities/{id}", s.getEntity)
	mux.HandleFunc("GET /v1/entities", s.listEntities)
	mux.HandleFunc("POST /v1/relationships", s.createRelationship)
	mux.HandleFunc("GET /v1/relationships", s.listRelationships)
	mux.HandleFunc("POST /v1/query", s.query)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.repository.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName,
			"dependencies": []map[string]any{{"name": "neo4j", "ok": false, "detail": err.Error()}},
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName,
		"dependencies": []map[string]any{{"name": "neo4j", "ok": true, "detail": "reachable"}},
	})
}

func (s *server) createEntity(w http.ResponseWriter, r *http.Request) {
	entity, err := decodeEntity(r.Body)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid entity")
		return
	}
	if entity.InvestigationID == "" || entity.Type == "" || entity.Type == "ENTITY_TYPE_UNSPECIFIED" {
		writeError(w, http.StatusBadRequest, "investigation_id and type are required")
		return
	}
	if entity.ID == "" {
		entity.ID = uuid.NewString()
	}
	now := s.now().UTC().Format(time.RFC3339Nano)
	if entity.CreatedAt == "" {
		entity.CreatedAt = now
	}
	entity.UpdatedAt = now
	if entity.Attributes == nil {
		entity.Attributes = map[string]string{}
	}
	if entity.EvidenceIDs == nil {
		entity.EvidenceIDs = []string{}
	}
	runID := s.start(r.Context(), "create-entity", entity.InvestigationID)
	created, err := s.repository.CreateEntity(r.Context(), entity)
	if err != nil {
		s.fail(r.Context(), runID, "create-entity", entity.InvestigationID)
		writeError(w, http.StatusBadGateway, "entity creation failed")
		return
	}
	s.complete(r.Context(), runID, "create-entity", entity.InvestigationID, created.ID, "DDU.ENTITY")
	writeJSON(w, http.StatusCreated, created)
}

func (s *server) getEntity(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	entity, err := s.repository.GetEntity(r.Context(), id)
	if err != nil || entity.ID == "" {
		writeError(w, http.StatusNotFound, "entity not found")
		return
	}
	runID := s.start(r.Context(), "get-entity", entity.InvestigationID)
	s.complete(r.Context(), runID, "get-entity", entity.InvestigationID, entity.ID, "DDU.ENTITY")
	writeJSON(w, http.StatusOK, entity)
}

func (s *server) listEntities(w http.ResponseWriter, r *http.Request) {
	investigationID := strings.TrimSpace(r.URL.Query().Get("investigation_id"))
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	runID := s.start(r.Context(), "list-entities", investigationID)
	entities, err := s.repository.ListEntities(r.Context(), investigationID, strings.TrimSpace(r.URL.Query().Get("type")))
	if err != nil {
		s.fail(r.Context(), runID, "list-entities", investigationID)
		writeError(w, http.StatusBadGateway, "entity listing failed")
		return
	}
	if entities == nil {
		entities = []Entity{}
	}
	s.complete(r.Context(), runID, "list-entities", investigationID, "", "")
	writeJSON(w, http.StatusOK, EntityList{Entities: entities})
}

func (s *server) createRelationship(w http.ResponseWriter, r *http.Request) {
	relationship, err := decodeRelationship(r.Body)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid relationship")
		return
	}
	if relationship.InvestigationID == "" || relationship.SourceEntityID == "" ||
		relationship.TargetEntityID == "" || relationship.RelationshipType == "" {
		writeError(w, http.StatusBadRequest, "investigation, endpoints, and relationship_type are required")
		return
	}
	if relationship.ID == "" {
		relationship.ID = uuid.NewString()
	}
	now := s.now().UTC().Format(time.RFC3339Nano)
	if relationship.CreatedAt == "" {
		relationship.CreatedAt = now
	}
	relationship.UpdatedAt = now
	if relationship.EvidenceIDs == nil {
		relationship.EvidenceIDs = []string{}
	}
	runID := s.start(r.Context(), "create-relationship", relationship.InvestigationID)
	created, err := s.repository.CreateRelationship(r.Context(), relationship)
	if err != nil {
		s.fail(r.Context(), runID, "create-relationship", relationship.InvestigationID)
		writeError(w, http.StatusBadGateway, "relationship creation failed")
		return
	}
	s.complete(r.Context(), runID, "create-relationship", relationship.InvestigationID, created.ID, "DDU.RELATIONSHIP")
	writeJSON(w, http.StatusCreated, created)
}

func (s *server) listRelationships(w http.ResponseWriter, r *http.Request) {
	investigationID := strings.TrimSpace(r.URL.Query().Get("investigation_id"))
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	runID := s.start(r.Context(), "list-relationships", investigationID)
	relationships, err := s.repository.ListRelationships(r.Context(), investigationID)
	if err != nil {
		s.fail(r.Context(), runID, "list-relationships", investigationID)
		writeError(w, http.StatusBadGateway, "relationship listing failed")
		return
	}
	if relationships == nil {
		relationships = []Relationship{}
	}
	s.complete(r.Context(), runID, "list-relationships", investigationID, "", "")
	writeJSON(w, http.StatusOK, RelationshipList{Relationships: relationships})
}

func (s *server) query(w http.ResponseWriter, r *http.Request) {
	var request QueryRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&request); err != nil || strings.TrimSpace(request.Cypher) == "" {
		writeError(w, http.StatusBadRequest, "cypher is required")
		return
	}
	if request.Parameters == nil {
		request.Parameters = map[string]any{}
	}
	runID := s.start(r.Context(), "query", "")
	records, err := s.repository.Query(r.Context(), request.Cypher, request.Parameters)
	if err != nil {
		s.fail(r.Context(), runID, "query", "")
		writeError(w, http.StatusBadRequest, "cypher query failed")
		return
	}
	if records == nil {
		records = []map[string]any{}
	}
	s.complete(r.Context(), runID, "query", "", "", "")
	writeJSON(w, http.StatusOK, QueryResponse{Records: records})
}

func decodeEntity(body io.Reader) (Entity, error) {
	data, err := io.ReadAll(io.LimitReader(body, 2<<20))
	if err != nil {
		return Entity{}, err
	}
	var envelope struct {
		Entity *Entity `json:"entity"`
	}
	if json.Unmarshal(data, &envelope) == nil && envelope.Entity != nil {
		return *envelope.Entity, nil
	}
	var entity Entity
	if err := json.Unmarshal(data, &entity); err != nil {
		return Entity{}, err
	}
	return entity, nil
}

func decodeRelationship(body io.Reader) (Relationship, error) {
	data, err := io.ReadAll(io.LimitReader(body, 2<<20))
	if err != nil {
		return Relationship{}, err
	}
	var envelope struct {
		Relationship *Relationship `json:"relationship"`
	}
	if json.Unmarshal(data, &envelope) == nil && envelope.Relationship != nil {
		return *envelope.Relationship, nil
	}
	var relationship Relationship
	if err := json.Unmarshal(data, &relationship); err != nil {
		return Relationship{}, err
	}
	return relationship, nil
}

func (s *server) start(ctx context.Context, job, investigationID string) string {
	runID := lineageemitter.NewRunID()
	s.emit(ctx, lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	})
	return runID
}

func (s *server) complete(ctx context.Context, runID, job, investigationID, outputID, outputType string) {
	event := lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":" + job,
		Facets: investigationFacet(investigationID),
	}
	if outputID != "" {
		event.Outputs = []lineageemitter.Output{{
			Namespace: investigationID, Name: outputID, Type: outputType,
		}}
	}
	s.emit(ctx, event)
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
