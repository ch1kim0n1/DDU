package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
	"github.com/google/uuid"
)

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	sherlock *sherlockAdapter
	lineage  lineageEmitter
	now      func() time.Time
}

func newHandler(lineage lineageEmitter) http.Handler {
	s := &server{sherlock: newSherlockAdapter(), lineage: lineage, now: time.Now}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", healthzHandler)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/discover", s.discover)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) discover(w http.ResponseWriter, r *http.Request) {
	var request DiscoverRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&request); err != nil {
		writeError(w, http.StatusBadRequest, "valid JSON body is required")
		return
	}
	if strings.TrimSpace(request.Username) == "" || strings.TrimSpace(request.InvestigationID) == "" {
		writeError(w, http.StatusBadRequest, "username and investigation_id are required")
		return
	}
	runID := s.start(r.Context(), "discover", request.InvestigationID, request.Username)
	accounts, err := s.sherlock.Search(r.Context(), request.Username, request.Sites)
	if err != nil {
		s.fail(r.Context(), runID, "discover", request.InvestigationID, request.Username)
		writeError(w, http.StatusBadGateway, "sherlock search failed")
		return
	}
	observations := s.buildObservations(accounts, request, runID)
	s.complete(r.Context(), runID, "discover", request.InvestigationID, request.Username)
	writeJSON(w, http.StatusOK, DiscoverResponse{Observations: observations})
}

func (s *server) buildObservations(accounts []CandidateAccount, request DiscoverRequest, runID string) []Observation {
	observedAt := s.now().UTC().Format(time.RFC3339Nano)
	extractionMethod := "sherlock-cli"
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		extractionMethod = "development-stub"
	}
	observations := make([]Observation, 0, len(accounts))
	for _, account := range accounts {
		obs := Observation{
			ID:                 uuid.NewString(),
			InvestigationID:    request.InvestigationID,
			EvidenceID:         request.Username,
			Type:               "OBSERVATION_TYPE_USERNAME",
			Label:              account.Username,
			DetectorConfidence: 1.0,
			Attributes: map[string]string{
				"platform":        account.Platform,
				"profile_url":     account.ProfileURL,
				"username":        account.Username,
				"epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
			},
			ObservedAt: observedAt,
			Provenance: Provenance{
				InvestigationID:   request.InvestigationID,
				ProducedByService: serviceName,
				ProducerVersion: ServiceVersion{
					Service:        serviceName,
					ServiceVersion: serviceVersion,
					Tool:           "sherlock",
					ToolVersion:    "0.14.0",
					Model:          model,
					ModelVersion:   modelVersion,
					GitCommit:      gitCommit,
					BuiltAt:        builtAt,
				},
				Tool:             "sherlock",
				ToolVersion:      "0.14.0",
				ProducedAt:       observedAt,
				RunID:            runID,
				JobName:          serviceName + ":discover",
				InputEvidenceIDs: []string{request.Username},
				ExtractionMethod: extractionMethod,
				Parameters:       map[string]string{"username": request.Username},
			},
		}
		observations = append(observations, obs)
	}
	return observations
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
