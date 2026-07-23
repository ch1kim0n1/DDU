package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (s *apiServer) processUsername(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input struct {
		Username string   `json:"username"`
		Sites    []string `json:"sites"`
		Modules  []string `json:"modules"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		strings.TrimSpace(input.Username) == "" {
		writeError(w, http.StatusBadRequest, "username is required")
		return
	}
	runID := s.start(r.Context(), "process-username", investigationID, []lineageemitter.Input{{
		Namespace: investigationID, Name: input.Username, Type: "DDU.SOURCE",
	}})
	observations, err := s.downstream.discoverUsername(
		r.Context(), investigationID, strings.TrimSpace(input.Username), input.Sites,
	)
	if err != nil {
		s.fail(r.Context(), runID, "process-username", investigationID)
		writeError(w, http.StatusBadGateway, "discovery failed: "+err.Error())
		return
	}
	enrichment, err := s.downstream.enrichOSINT(
		r.Context(), investigationID, strings.TrimSpace(input.Username), input.Modules,
	)
	if err != nil {
		s.fail(r.Context(), runID, "process-username", investigationID)
		writeError(w, http.StatusBadGateway, "osint enrichment failed: "+err.Error())
		return
	}
	observations = append(observations, enrichment...)
	entities := make([]Entity, 0, len(observations))
	for _, observation := range observations {
		created, createErr := s.downstream.createEntity(r.Context(), observationEntity(observation))
		if createErr != nil {
			s.fail(r.Context(), runID, "process-username", investigationID)
			writeError(w, http.StatusBadGateway, "entity persistence failed: "+createErr.Error())
			return
		}
		entities = append(entities, created)
	}
	outputs := make([]lineageemitter.Output, 0, len(entities))
	for _, entity := range entities {
		outputs = append(outputs, lineageemitter.Output{
			Namespace: investigationID, Name: entity.ID, Type: "DDU.ENTITY",
		})
	}
	s.complete(r.Context(), runID, "process-username", investigationID, outputs)
	writeJSON(w, http.StatusCreated, map[string]any{
		"username":     input.Username,
		"observations": observations,
		"entities":     entities,
	})
}

func (s *apiServer) processURL(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input struct {
		URL    string `json:"url"`
		Mode   string `json:"mode"` // collect | capture | auto
		Process bool  `json:"process"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		strings.TrimSpace(input.URL) == "" {
		writeError(w, http.StatusBadRequest, "url is required")
		return
	}
	mode := strings.ToLower(strings.TrimSpace(input.Mode))
	if mode == "" {
		mode = "auto"
	}
	runID := s.start(r.Context(), "process-url", investigationID, []lineageemitter.Input{{
		Namespace: investigationID, Name: input.URL, Type: "DDU.SOURCE",
	}})
	evidenceList := []Evidence{}
	switch mode {
	case "capture":
		evidence, err := s.downstream.captureURL(r.Context(), investigationID, input.URL)
		if err != nil {
			s.fail(r.Context(), runID, "process-url", investigationID)
			writeError(w, http.StatusBadGateway, "webcapture failed: "+err.Error())
			return
		}
		evidenceList = append(evidenceList, evidence)
	case "collect", "auto":
		collected, err := s.downstream.collectURL(r.Context(), investigationID, input.URL)
		if err != nil || len(collected) == 0 {
			if mode == "collect" {
				s.fail(r.Context(), runID, "process-url", investigationID)
				writeError(w, http.StatusBadGateway, "collector failed: "+errString(err))
				return
			}
			evidence, captureErr := s.downstream.captureURL(r.Context(), investigationID, input.URL)
			if captureErr != nil {
				s.fail(r.Context(), runID, "process-url", investigationID)
				writeError(w, http.StatusBadGateway, "url acquisition failed")
				return
			}
			evidenceList = append(evidenceList, evidence)
		} else {
			evidenceList = append(evidenceList, collected...)
		}
	default:
		writeError(w, http.StatusBadRequest, "mode must be collect, capture, or auto")
		return
	}

	allObservations := []Observation{}
	allEntities := []Entity{}
	if input.Process {
		for _, evidence := range evidenceList {
			if !strings.HasPrefix(evidence.MimeType, "image/") {
				continue
			}
			observations, entities, processErr := s.runPerception(
				r.Context(), investigationID, evidence.ID,
			)
			if processErr != nil {
				s.fail(r.Context(), runID, "process-url", investigationID)
				writeError(w, http.StatusBadGateway, processErr.Error())
				return
			}
			allObservations = append(allObservations, observations...)
			allEntities = append(allEntities, entities...)
		}
	}
	outputs := []lineageemitter.Output{}
	for _, evidence := range evidenceList {
		outputs = append(outputs, lineageemitter.Output{
			Namespace: investigationID, Name: evidence.ID, Type: "DDU.EVIDENCE",
		})
	}
	s.complete(r.Context(), runID, "process-url", investigationID, outputs)
	writeJSON(w, http.StatusCreated, map[string]any{
		"evidence":     evidenceList,
		"observations": allObservations,
		"entities":     allEntities,
	})
}

func (s *apiServer) resolveInvestigation(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input struct {
		EntityIDs []string `json:"entity_ids"`
		Threshold float64  `json:"threshold"`
	}
	_ = json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input)
	if input.Threshold <= 0 {
		input.Threshold = 0.5
	}
	runID := s.start(r.Context(), "resolve", investigationID, nil)
	candidates, err := s.downstream.resolveEntities(
		r.Context(), investigationID, input.EntityIDs, input.Threshold,
	)
	if err != nil {
		s.fail(r.Context(), runID, "resolve", investigationID)
		writeError(w, http.StatusBadGateway, "resolution failed: "+err.Error())
		return
	}
	persisted := make([]Relationship, 0, len(candidates))
	for _, candidate := range candidates {
		relationship := Relationship{
			ID:                candidate.ID,
			InvestigationID:   investigationID,
			SourceEntityID:    candidate.SourceEntityID,
			TargetEntityID:    candidate.TargetEntityID,
			RelationshipType:  candidate.RelationshipType,
			VerificationState: "VERIFICATION_STATE_PENDING",
			Confidence:        candidate.Confidence,
			EvidenceIDs:       candidate.EvidenceIDs,
			CandidateRelationshipID: candidate.ID,
			Provenance:        candidate.Provenance,
			CreatedAt:         candidate.CreatedAt,
			UpdatedAt:         candidate.CreatedAt,
		}
		if relationship.EvidenceIDs == nil {
			relationship.EvidenceIDs = []string{}
		}
		created, createErr := s.downstream.createRelationship(r.Context(), relationship)
		if createErr != nil {
			s.fail(r.Context(), runID, "resolve", investigationID)
			writeError(w, http.StatusBadGateway, "relationship persistence failed: "+createErr.Error())
			return
		}
		persisted = append(persisted, created)
	}
	s.complete(r.Context(), runID, "resolve", investigationID, nil)
	writeJSON(w, http.StatusCreated, map[string]any{
		"candidates":    candidates,
		"relationships": persisted,
	})
}

func (s *apiServer) verifyRelationship(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	relationshipID := chi.URLParam(r, "relationshipID")
	var input struct {
		State string `json:"verification_state"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil {
		writeError(w, http.StatusBadRequest, "verification_state is required")
		return
	}
	state := strings.ToUpper(strings.TrimSpace(input.State))
	switch state {
	case "VERIFICATION_STATE_VERIFIED", "VERIFICATION_STATE_REJECTED", "VERIFIED", "REJECTED":
	default:
		writeError(w, http.StatusBadRequest, "verification_state must be verified or rejected")
		return
	}
	if state == "VERIFIED" {
		state = "VERIFICATION_STATE_VERIFIED"
	}
	if state == "REJECTED" {
		state = "VERIFICATION_STATE_REJECTED"
	}
	actor := roleFromRequest(r)
	runID := s.start(r.Context(), "verify-relationship", investigationID, nil)
	updated, err := s.downstream.updateRelationshipVerification(
		r.Context(), relationshipID, state, actor,
	)
	if err != nil {
		s.fail(r.Context(), runID, "verify-relationship", investigationID)
		writeError(w, http.StatusBadGateway, "verification update failed: "+err.Error())
		return
	}
	s.complete(r.Context(), runID, "verify-relationship", investigationID, []lineageemitter.Output{{
		Namespace: investigationID, Name: updated.ID, Type: "DDU.RELATIONSHIP",
	}})
	writeJSON(w, http.StatusOK, updated)
}

func (s *apiServer) contradictInvestigation(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	runID := s.start(r.Context(), "contradict", investigationID, nil)
	contradictions, err := s.downstream.contradict(r.Context(), investigationID)
	if err != nil {
		s.fail(r.Context(), runID, "contradict", investigationID)
		writeError(w, http.StatusBadGateway, "contradiction engine failed: "+err.Error())
		return
	}
	s.complete(r.Context(), runID, "contradict", investigationID, nil)
	writeJSON(w, http.StatusOK, map[string]any{"contradictions": contradictions})
}

func (s *apiServer) timeline(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	events, err := s.downstream.temporalTimeline(r.Context(), investigationID)
	if err != nil {
		// Fall back to observation-derived timeline when temporal is unavailable.
		entities, listErr := s.downstream.listEntities(r.Context(), investigationID, "ENTITY_TYPE_OBSERVATION")
		if listErr != nil {
			writeError(w, http.StatusBadGateway, err.Error())
			return
		}
		events = make([]map[string]any, 0, len(entities.Entities))
		for _, entity := range entities.Entities {
			events = append(events, map[string]any{
				"id":         entity.ID,
				"timestamp":  entity.Attributes["observed_at"],
				"label":      entity.Attributes["label"],
				"type":       entity.Attributes["observation_type"],
				"entity_id":  entity.ID,
				"evidence_id": entity.Attributes["evidence_id"],
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"events": events})
}

func (s *apiServer) createSnapshot(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input struct {
		Label string `json:"label"`
	}
	_ = json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input)
	runID := s.start(r.Context(), "snapshot", investigationID, nil)
	snapshot, err := s.downstream.createSnapshot(r.Context(), investigationID, input.Label)
	if err != nil {
		s.fail(r.Context(), runID, "snapshot", investigationID)
		writeError(w, http.StatusBadGateway, "snapshot failed: "+err.Error())
		return
	}
	s.complete(r.Context(), runID, "snapshot", investigationID, nil)
	writeJSON(w, http.StatusCreated, snapshot)
}

func (s *apiServer) listSnapshots(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	snapshots, err := s.downstream.listSnapshots(r.Context(), investigationID)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"snapshots": snapshots})
}

func (s *apiServer) generateReport(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	investigation, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	runID := s.start(r.Context(), "report", investigationID, nil)
	entities, err := s.downstream.listEntities(r.Context(), investigationID, "")
	if err != nil {
		s.fail(r.Context(), runID, "report", investigationID)
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	relationships, err := s.downstream.listRelationships(r.Context(), investigationID)
	if err != nil {
		s.fail(r.Context(), runID, "report", investigationID)
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	evidence, err := s.downstream.listEvidence(r.Context(), investigationID)
	if err != nil {
		s.fail(r.Context(), runID, "report", investigationID)
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	report := map[string]any{
		"id":              uuid.NewString(),
		"investigation_id": investigationID,
		"title":           investigation.Name,
		"generated_at":    time.Now().UTC().Format(time.RFC3339Nano),
		"generated_by":    roleFromRequest(r),
		"summary": map[string]any{
			"entity_count":       len(entities.Entities),
			"relationship_count": len(relationships.Relationships),
			"evidence_count":     len(evidence),
		},
		"entities":       entities.Entities,
		"relationships":  relationships.Relationships,
		"evidence":       evidence,
		"epistemic_note": "Candidate relationships remain unverified unless explicitly promoted.",
	}
	s.complete(r.Context(), runID, "report", investigationID, nil)
	writeJSON(w, http.StatusOK, report)
}

func (s *apiServer) replayInvestigation(w http.ResponseWriter, r *http.Request) {
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
	writeJSON(w, http.StatusOK, map[string]any{
		"investigation_id": investigationID,
		"replay":           runs.Runs,
		"count":            runs.Count,
	})
}

func (s *apiServer) runAgent(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input struct {
		Mode       string         `json:"mode"` // image | autonomous | template | query
		EvidenceID string         `json:"evidence_id"`
		Template   string         `json:"template"`
		Query      string         `json:"query"`
		Prompts    []string       `json:"prompts"`
		Params     map[string]any `json:"params"`
	}
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil {
		writeError(w, http.StatusBadRequest, "valid JSON body is required")
		return
	}
	mode := strings.ToLower(strings.TrimSpace(input.Mode))
	if mode == "" {
		mode = "image"
	}
	runID := s.start(r.Context(), "agent-"+mode, investigationID, nil)
	payload := map[string]any{
		"investigation_id": investigationID,
		"evidence_id":      input.EvidenceID,
		"prompts":          input.Prompts,
		"template":         input.Template,
		"query":            input.Query,
		"params":           input.Params,
		"launched_by_role": roleFromRequest(r),
	}
	endpoint := "/v1/workflow/image"
	switch mode {
	case "autonomous":
		endpoint = "/v1/workflow/autonomous"
	case "template":
		endpoint = "/v1/workflow/template"
	case "query":
		endpoint = "/v1/query"
	case "image":
		endpoint = "/v1/workflow/image"
	default:
		writeError(w, http.StatusBadRequest, "unsupported agent mode")
		return
	}
	result, err := s.downstream.runAgentWorkflow(r.Context(), endpoint, payload)
	if err != nil {
		s.fail(r.Context(), runID, "agent-"+mode, investigationID)
		writeError(w, http.StatusBadGateway, "agent failed: "+err.Error())
		return
	}
	s.complete(r.Context(), runID, "agent-"+mode, investigationID, nil)
	writeJSON(w, http.StatusOK, result)
}

func (s *apiServer) manageMembers(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	investigation, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	if r.Method == http.MethodGet {
		members := append([]InvestigationMember{}, investigation.Members...)
		writeJSON(w, http.StatusOK, map[string]any{"members": members})
		return
	}
	var input InvestigationMember
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil ||
		strings.TrimSpace(input.UserID) == "" {
		writeError(w, http.StatusBadRequest, "user_id is required")
		return
	}
	if input.Role == "" {
		input.Role = RoleViewer
	}
	input.AddedAt = time.Now().UTC().Format(time.RFC3339Nano)
	current := investigation
	replaced := false
	for i, member := range current.Members {
		if member.UserID == input.UserID {
			current.Members[i] = input
			replaced = true
			break
		}
	}
	if !replaced {
		current.Members = append(current.Members, input)
	}
	_ = s.store.Put(r.Context(), current)
	s.audit(r, "UPSERT_MEMBER", "InvestigationMember", input.UserID, http.StatusOK)
	writeJSON(w, http.StatusOK, input)
}

func (s *apiServer) listOntologyTypes(w http.ResponseWriter, r *http.Request) {
	body, err := s.downstream.listOntologyTypes(r.Context(), r.URL.Query().Get("investigation_id"))
	if err != nil {
		writeError(w, http.StatusBadGateway, "ontology service unavailable: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, body)
}

func (s *apiServer) createOntologyType(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	if _, ok := s.investigation(investigationID); !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}
	var input map[string]any
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil {
		writeError(w, http.StatusBadRequest, "valid JSON body is required")
		return
	}
	input["investigation_id"] = investigationID
	runID := s.start(r.Context(), "ontology-create-type", investigationID, nil)
	created, err := s.downstream.createOntologyType(r.Context(), input)
	if err != nil {
		s.fail(r.Context(), runID, "ontology-create-type", investigationID)
		writeError(w, http.StatusBadGateway, "ontology type creation failed: "+err.Error())
		return
	}
	s.complete(r.Context(), runID, "ontology-create-type", investigationID, nil)
	writeJSON(w, http.StatusCreated, created)
}

func (s *apiServer) listPlugins(w http.ResponseWriter, r *http.Request) {
	s.pluginMtx.RLock()
	defer s.pluginMtx.RUnlock()

	plugins := make([]Plugin, 0, len(s.plugins))
	for _, plugin := range s.plugins {
		plugins = append(plugins, plugin)
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"plugins": plugins,
		"sdk": map[string]any{
			"contract": "Register a ddu-* service exposing /healthz, /versionz, and lineage events.",
			"version":  "1.0.0",
			"endpoints": map[string]string{
				"register":   "POST /v1/plugins",
				"deregister": "DELETE /v1/plugins/{id}",
				"list":       "GET /v1/plugins",
			},
		},
	})
}

func (s *apiServer) registerPlugin(w http.ResponseWriter, r *http.Request) {
	var plugin Plugin
	if err := json.NewDecoder(r.Body).Decode(&plugin); err != nil {
		writeError(w, http.StatusBadRequest, "invalid plugin registration request")
		return
	}

	if plugin.ID == "" {
		writeError(w, http.StatusBadRequest, "plugin id is required")
		return
	}
	if plugin.Name == "" {
		writeError(w, http.StatusBadRequest, "plugin name is required")
		return
	}
	if plugin.Endpoint == "" {
		writeError(w, http.StatusBadRequest, "plugin endpoint is required")
		return
	}

	s.pluginMtx.Lock()
	defer s.pluginMtx.Unlock()

	if _, exists := s.plugins[plugin.ID]; exists {
		writeError(w, http.StatusConflict, "plugin with this id already exists")
		return
	}

	plugin.RegisteredAt = time.Now().UTC().Format(time.RFC3339)
	if plugin.Metadata == nil {
		plugin.Metadata = make(map[string]string)
	}

	s.plugins[plugin.ID] = plugin

	writeJSON(w, http.StatusCreated, plugin)
}

func (s *apiServer) deregisterPlugin(w http.ResponseWriter, r *http.Request) {
	pluginID := chi.URLParam(r, "id")
	if pluginID == "" {
		writeError(w, http.StatusBadRequest, "plugin id is required")
		return
	}

	s.pluginMtx.Lock()
	defer s.pluginMtx.Unlock()

	if _, exists := s.plugins[pluginID]; !exists {
		writeError(w, http.StatusNotFound, "plugin not found")
		return
	}

	delete(s.plugins, pluginID)

	writeJSON(w, http.StatusOK, map[string]string{"id": pluginID, "status": "deregistered"})
}

func (s *apiServer) getRetentionPolicy(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	inv, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"investigation_id": investigationID,
		"retention_policy": inv.RetentionPolicy,
	})
}

func (s *apiServer) setRetentionPolicy(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	inv, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}

	var policy RetentionPolicy
	if err := json.NewDecoder(r.Body).Decode(&policy); err != nil {
		writeError(w, http.StatusBadRequest, "invalid retention policy request")
		return
	}

	if policy.RetentionDays < 0 {
		writeError(w, http.StatusBadRequest, "retention_days must be non-negative")
		return
	}

	inv.RetentionPolicy = policy
	s.store.Put(r.Context(), inv)

	writeJSON(w, http.StatusOK, map[string]any{
		"investigation_id": investigationID,
		"retention_policy": policy,
	})
}

func (s *apiServer) exportInvestigation(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	inv, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}

	var req ExportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid export request")
		return
	}

	if req.Format == "" {
		req.Format = "json"
	}
	if req.Scope == "" {
		req.Scope = "summary"
	}

	exportData := map[string]any{
		"investigation_id": investigationID,
		"name":             inv.Name,
		"created_at":       inv.CreatedAt,
		"export_format":    req.Format,
		"export_scope":     req.Scope,
		"exported_at":      time.Now().UTC().Format(time.RFC3339),
	}

	if req.Scope == "full" || req.Scope == "evidence_only" {
		evidence, err := s.downstream.listEvidence(r.Context(), investigationID)
		if err == nil {
			exportData["evidence"] = evidence
		}
	}

	if req.Scope == "full" {
		entities, err := s.downstream.listEntities(r.Context(), investigationID, "")
		if err == nil {
			exportData["entities"] = entities.Entities
		}
		relationships, err := s.downstream.listRelationships(r.Context(), investigationID)
		if err == nil {
			exportData["relationships"] = relationships.Relationships
		}
	}

	switch req.Format {
	case "json":
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=investigation_%s.json", investigationID))
		json.NewEncoder(w).Encode(exportData)
	case "csv":
		w.Header().Set("Content-Type", "text/csv")
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=investigation_%s.csv", investigationID))
		writeJSON(w, http.StatusNotImplemented, map[string]string{"error": "CSV export not yet implemented"})
	default:
		writeError(w, http.StatusBadRequest, "unsupported export format")
	}
}

func (s *apiServer) deleteInvestigation(w http.ResponseWriter, r *http.Request) {
	investigationID := chi.URLParam(r, "id")
	inv, ok := s.investigation(investigationID)
	if !ok {
		writeError(w, http.StatusNotFound, "investigation not found")
		return
	}

	if inv.RetentionPolicy.ExportRequired {
		writeError(w, http.StatusForbidden, "investigation requires export before deletion per retention policy")
		return
	}

	s.store.mu.Lock()
	delete(s.store.cache, investigationID)
	s.store.mu.Unlock()

	writeJSON(w, http.StatusOK, map[string]string{
		"investigation_id": investigationID,
		"status":          "deleted",
	})
}

func (s *apiServer) runPerception(
	ctx context.Context,
	investigationID, evidenceID string,
) ([]Observation, []Entity, error) {
	request := map[string]any{"evidence_id": evidenceID, "investigation_id": investigationID}
	calls := []struct {
		service, baseURL, endpoint string
		payload                    map[string]any
	}{
		{"ddu-vision", s.downstream.urls.Vision, "/v1/detect", map[string]any{
			"evidence_id": evidenceID, "investigation_id": investigationID,
			"prompts": []string{"person", "vehicle", "object"},
		}},
		{"ddu-ocr", s.downstream.urls.OCR, "/v1/ocr", request},
		{"ddu-geo", s.downstream.urls.Geo, "/v1/locate", map[string]any{
			"evidence_id": evidenceID, "investigation_id": investigationID, "top_k": 5,
		}},
	}
	type inferenceResult struct {
		service      string
		observations []Observation
		err          error
	}
	results := make(chan inferenceResult, len(calls))
	for _, call := range calls {
		go func(call struct {
			service, baseURL, endpoint string
			payload                    map[string]any
		}) {
			observations, invokeErr := s.downstream.invokeML(
				ctx, call.baseURL, call.endpoint, call.payload,
			)
			results <- inferenceResult{call.service, observations, invokeErr}
		}(call)
	}
	observations := make([]Observation, 0)
	for range calls {
		result := <-results
		if result.err != nil {
			return nil, nil, result.err
		}
		observations = append(observations, result.observations...)
	}
	entities := make([]Entity, 0, len(observations))
	for _, observation := range observations {
		created, err := s.downstream.createEntity(ctx, observationEntity(observation))
		if err != nil {
			return nil, nil, err
		}
		entities = append(entities, created)
	}
	_ = s.embedObservations(ctx, investigationID, evidenceID, observations)
	return observations, entities, nil
}

func (s *apiServer) embedObservations(
	ctx context.Context,
	investigationID, evidenceID string,
	observations []Observation,
) error {
	if s.downstream.urls.Vector == "" {
		return nil
	}
	collection := "investigation-" + investigationID
	_ = s.downstream.ensureCollection(ctx, investigationID, collection, 8)
	points := make([]map[string]any, 0, len(observations))
	for _, observation := range observations {
		vector := placeholderEmbedding(observation.Label + ":" + observation.Type)
		points = append(points, map[string]any{
			"id":     observation.ID,
			"vector": vector,
			"payload": map[string]any{
				"investigation_id": investigationID,
				"evidence_id":      evidenceID,
				"label":            observation.Label,
				"type":             observation.Type,
				"embedding_source": "api-placeholder",
			},
		})
	}
	if len(points) == 0 {
		return nil
	}
	return s.downstream.upsertVectors(ctx, investigationID, collection, points)
}

func placeholderEmbedding(text string) []float32 {
	vector := make([]float32, 8)
	for i, r := range text {
		vector[i%len(vector)] += float32(int(r)%97) / 97.0
	}
	return vector
}

func errString(err error) string {
	if err == nil {
		return "no media acquired"
	}
	return err.Error()
}
