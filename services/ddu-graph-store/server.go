package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
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
	UpdateRelationshipVerification(context.Context, string, string, string) (Relationship, error)
	Query(context.Context, string, map[string]any) ([]map[string]any, error)
	Close(context.Context) error
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type graphSnapshot struct {
	ID              string         `json:"id"`
	InvestigationID string         `json:"investigation_id"`
	Label           string         `json:"label"`
	CreatedAt       string         `json:"created_at"`
	EntityCount     int            `json:"entity_count"`
	RelationshipCount int          `json:"relationship_count"`
	Entities        []Entity       `json:"entities"`
	Relationships   []Relationship `json:"relationships"`
}

type EvidenceDependency struct {
	ID              string            `json:"id"`
	ParentEvidenceID string            `json:"parent_evidence_id"`
	ChildEvidenceID  string            `json:"child_evidence_id"`
	InvestigationID  string            `json:"investigation_id"`
	DependencyType  string            `json:"dependency_type"` // DERIVED, CONTAINS, REFERENCES
	CreatedAt       string            `json:"created_at"`
}

type server struct {
	repository graphRepository
	lineage    lineageEmitter
	now        func() time.Time
	snapshots  map[string]graphSnapshot
	dependencies map[string][]EvidenceDependency
	depMtx     sync.RWMutex
}

func newHandler(repository graphRepository, lineage lineageEmitter) http.Handler {
	s := &server{
		repository: repository,
		lineage:    lineage,
		now:        time.Now,
		snapshots:  map[string]graphSnapshot{},
		dependencies: make(map[string][]EvidenceDependency),
		depMtx:     sync.RWMutex{},
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/entities", s.createEntity)
	mux.HandleFunc("GET /v1/entities/{id}", s.getEntity)
	mux.HandleFunc("GET /v1/entities", s.listEntities)
	mux.HandleFunc("POST /v1/relationships", s.createRelationship)
	mux.HandleFunc("GET /v1/relationships", s.listRelationships)
	mux.HandleFunc("PATCH /v1/relationships/{id}/verification", s.verifyRelationship)
	mux.HandleFunc("POST /v1/snapshots", s.createSnapshot)
	mux.HandleFunc("GET /v1/snapshots", s.listSnapshots)
	mux.HandleFunc("POST /v1/query", s.query)
	mux.HandleFunc("POST /v1/evidence-dependencies", s.createEvidenceDependency)
	mux.HandleFunc("GET /v1/evidence-dependencies/{investigation_id}", s.listEvidenceDependencies)
	mux.HandleFunc("GET /v1/evidence-dependencies/{investigation_id}/{evidence_id}/downstream", s.getDownstreamDependencies)
	mux.HandleFunc("DELETE /v1/evidence-dependencies/{evidence_id}", s.invalidateEvidence)
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

func (s *server) verifyRelationship(w http.ResponseWriter, r *http.Request) {
	relationshipID := strings.TrimSpace(r.PathValue("id"))
	var input struct {
		VerificationState string `json:"verification_state"`
		VerifiedBy        string `json:"verified_by"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		relationshipID == "" || strings.TrimSpace(input.VerificationState) == "" {
		writeError(w, http.StatusBadRequest, "relationship id and verification_state are required")
		return
	}
	runID := s.start(r.Context(), "verify-relationship", "")
	updated, err := s.repository.UpdateRelationshipVerification(
		r.Context(), relationshipID, input.VerificationState, input.VerifiedBy,
	)
	if err != nil {
		s.fail(r.Context(), runID, "verify-relationship", "")
		writeError(w, http.StatusBadGateway, "verification update failed")
		return
	}
	s.complete(r.Context(), runID, "verify-relationship", updated.InvestigationID, updated.ID, "DDU.RELATIONSHIP")
	writeJSON(w, http.StatusOK, updated)
}

func (s *server) createSnapshot(w http.ResponseWriter, r *http.Request) {
	var input struct {
		InvestigationID string `json:"investigation_id"`
		Label           string `json:"label"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		strings.TrimSpace(input.InvestigationID) == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	runID := s.start(r.Context(), "create-snapshot", input.InvestigationID)
	entities, err := s.repository.ListEntities(r.Context(), input.InvestigationID, "")
	if err != nil {
		s.fail(r.Context(), runID, "create-snapshot", input.InvestigationID)
		writeError(w, http.StatusBadGateway, "snapshot entity listing failed")
		return
	}
	relationships, err := s.repository.ListRelationships(r.Context(), input.InvestigationID)
	if err != nil {
		s.fail(r.Context(), runID, "create-snapshot", input.InvestigationID)
		writeError(w, http.StatusBadGateway, "snapshot relationship listing failed")
		return
	}
	if entities == nil {
		entities = []Entity{}
	}
	if relationships == nil {
		relationships = []Relationship{}
	}
	snapshot := graphSnapshot{
		ID:                uuid.NewString(),
		InvestigationID:   input.InvestigationID,
		Label:             input.Label,
		CreatedAt:         s.now().UTC().Format(time.RFC3339Nano),
		EntityCount:       len(entities),
		RelationshipCount: len(relationships),
		Entities:          entities,
		Relationships:     relationships,
	}
	s.snapshots[snapshot.ID] = snapshot
	_ = s.persistSnapshot(r.Context(), snapshot)
	s.complete(r.Context(), runID, "create-snapshot", input.InvestigationID, snapshot.ID, "DDU.SNAPSHOT")
	writeJSON(w, http.StatusCreated, snapshot)
}

func (s *server) listSnapshots(w http.ResponseWriter, r *http.Request) {
	investigationID := strings.TrimSpace(r.URL.Query().Get("investigation_id"))
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	_ = s.loadSnapshots(r.Context(), investigationID)
	snapshots := make([]graphSnapshot, 0)
	for _, snapshot := range s.snapshots {
		if snapshot.InvestigationID == investigationID {
			snapshots = append(snapshots, snapshot)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"snapshots": snapshots})
}

func (s *server) persistSnapshot(ctx context.Context, snapshot graphSnapshot) error {
	payload, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	_, err = s.repository.Query(ctx, `
		MERGE (s:GraphSnapshot {id: $id})
		SET s.investigation_id = $investigation_id,
		    s.label = $label,
		    s.created_at = $created_at,
		    s.entity_count = $entity_count,
		    s.relationship_count = $relationship_count,
		    s.payload = $payload
	`, map[string]any{
		"id":                 snapshot.ID,
		"investigation_id":   snapshot.InvestigationID,
		"label":              snapshot.Label,
		"created_at":         snapshot.CreatedAt,
		"entity_count":       snapshot.EntityCount,
		"relationship_count": snapshot.RelationshipCount,
		"payload":            string(payload),
	})
	return err
}

func (s *server) loadSnapshots(ctx context.Context, investigationID string) error {
	records, err := s.repository.Query(ctx, `
		MATCH (s:GraphSnapshot {investigation_id: $investigation_id})
		RETURN s.id AS id, s.payload AS payload
	`, map[string]any{"investigation_id": investigationID})
	if err != nil {
		return err
	}
	for _, record := range records {
		raw, _ := record["payload"].(string)
		if raw == "" {
			continue
		}
		var snapshot graphSnapshot
		if json.Unmarshal([]byte(raw), &snapshot) != nil {
			continue
		}
		s.snapshots[snapshot.ID] = snapshot
	}
	return nil
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

func decodeJSON(body io.Reader, target any) error {
	data, err := io.ReadAll(io.LimitReader(body, 2<<20))
	if err != nil {
		return err
	}
	return json.Unmarshal(data, target)
}

func (s *server) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func (s *server) createEvidenceDependency(w http.ResponseWriter, r *http.Request) {
	var dependency struct {
		ParentEvidenceID string `json:"parent_evidence_id"`
		ChildEvidenceID  string `json:"child_evidence_id"`
		InvestigationID  string `json:"investigation_id"`
		DependencyType  string `json:"dependency_type"`
	}
	if err := decodeJSON(r.Body, &dependency); err != nil {
		writeError(w, http.StatusBadRequest, "invalid dependency request")
		return
	}
	
	if dependency.ParentEvidenceID == "" || dependency.ChildEvidenceID == "" || dependency.InvestigationID == "" {
		writeError(w, http.StatusBadRequest, "parent_evidence_id, child_evidence_id, and investigation_id are required")
		return
	}
	
	if dependency.DependencyType == "" {
		dependency.DependencyType = "DERIVED"
	}
	
	s.depMtx.Lock()
	if s.dependencies[dependency.InvestigationID] == nil {
		s.dependencies[dependency.InvestigationID] = []EvidenceDependency{}
	}
	
	newDep := EvidenceDependency{
		ID:              uuid.NewString(),
		ParentEvidenceID: dependency.ParentEvidenceID,
		ChildEvidenceID:  dependency.ChildEvidenceID,
		InvestigationID:  dependency.InvestigationID,
		DependencyType:  dependency.DependencyType,
		CreatedAt:       s.now().UTC().Format(time.RFC3339),
	}
	s.dependencies[dependency.InvestigationID] = append(s.dependencies[dependency.InvestigationID], newDep)
	s.depMtx.Unlock()
	
	writeJSON(w, http.StatusCreated, newDep)
}

func (s *server) listEvidenceDependencies(w http.ResponseWriter, r *http.Request) {
	investigationID := r.PathValue("investigation_id")
	s.depMtx.RLock()
	deps := s.dependencies[investigationID]
	s.depMtx.RUnlock()
	
	writeJSON(w, http.StatusOK, map[string]any{
		"investigation_id": investigationID,
		"dependencies": deps,
		"total_dependencies": len(deps),
	})
}

func (s *server) getDownstreamDependencies(w http.ResponseWriter, r *http.Request) {
	investigationID := r.PathValue("investigation_id")
	evidenceID := r.PathValue("evidence_id")
	
	s.depMtx.RLock()
	deps := s.dependencies[investigationID]
	s.depMtx.Unlock()
	
	downstream := []EvidenceDependency{}
	for _, dep := range deps {
		if dep.ParentEvidenceID == evidenceID {
			downstream = append(downstream, dep)
			// Recursively get downstream of this child
			// This is simplified; in production would use proper graph traversal
		}
	}
	
	writeJSON(w, http.StatusOK, map[string]any{
		"investigation_id": investigationID,
		"evidence_id": evidenceID,
		"downstream_dependencies": downstream,
		"total_downstream": len(downstream),
	})
}

func (s *server) invalidateEvidence(w http.ResponseWriter, r *http.Request) {
	evidenceID := r.PathValue("id")
	
	s.depMtx.Lock()
	defer s.depMtx.Unlock()
	
	affectedInvestigations := []string{}
	for invID, deps := range s.dependencies {
		for i, dep := range deps {
			if dep.ParentEvidenceID == evidenceID || dep.ChildEvidenceID == evidenceID {
				// Mark as invalidated
				deps[i].DependencyType = "INVALIDATED"
				affectedInvestigations = append(affectedInvestigations, invID)
			}
		}
	}
	
	writeJSON(w, http.StatusOK, map[string]any{
		"evidence_id": evidenceID,
		"invalidated": true,
		"affected_investigations": affectedInvestigations,
		"affected_investigation_count": len(affectedInvestigations),
	})
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
