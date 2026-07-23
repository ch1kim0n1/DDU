package main

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
)

var highRiskIntelPaths = map[string]bool{
	"location/current": true,
	"household":        true,
	"property":         true,
	"identity/resolve": true,
	"pattern-of-life":  true,
	"temporal/diff":    true,
	"location/history": true,
	"social-circle":    true,
	"aliases":          true,
	"records/fuse":     true,
}

func (s *apiServer) requireIntelAuthorization(w http.ResponseWriter, r *http.Request, feature string) bool {
	purpose := strings.TrimSpace(r.Header.Get("X-DDU-Authorization-Purpose"))
	if purpose == "" {
		var body struct {
			AuthorizationPurpose string `json:"authorization_purpose"`
		}
		// Body may be re-read by caller; only inspect header for gate.
		_ = body
	}
	if highRiskIntelPaths[feature] && purpose == "" {
		writeJSON(w, http.StatusForbidden, map[string]any{
			"error":   "high-risk capability requires X-DDU-Authorization-Purpose",
			"feature": feature,
			"risk":    "S/A",
		})
		return false
	}
	return true
}

func (s *apiServer) intelProxy(feature, endpoint string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		investigationID := chi.URLParam(r, "id")
		if _, ok := s.investigation(investigationID); !ok {
			writeError(w, http.StatusNotFound, "investigation not found")
			return
		}
		if !s.requireIntelAuthorization(w, r, feature) {
			return
		}
		raw, err := io.ReadAll(io.LimitReader(r.Body, 2<<20))
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid body")
			return
		}
		payload := map[string]any{}
		if len(strings.TrimSpace(string(raw))) > 0 {
			if err := json.Unmarshal(raw, &payload); err != nil {
				writeError(w, http.StatusBadRequest, "valid JSON body is required")
				return
			}
		}
		payload["investigation_id"] = investigationID
		if purpose := strings.TrimSpace(r.Header.Get("X-DDU-Authorization-Purpose")); purpose != "" {
			if _, ok := payload["authorization_purpose"]; !ok {
				payload["authorization_purpose"] = purpose
			}
		}
		if _, ok := payload["authorization_purpose"]; !ok || strings.TrimSpace(strAny(payload["authorization_purpose"])) == "" {
			payload["authorization_purpose"] = "investigation"
		}
		runID := s.start(r.Context(), "intel-"+feature, investigationID, nil)
		result, err := s.downstream.intelPOST(r.Context(), endpoint, payload)
		if err != nil {
			s.fail(r.Context(), runID, "intel-"+feature, investigationID)
			writeError(w, http.StatusBadGateway, "intel failed: "+err.Error())
			return
		}
		s.complete(r.Context(), runID, "intel-"+feature, investigationID, nil)
		writeJSON(w, http.StatusOK, result)
	}
}

func (s *apiServer) intelGET(feature, endpoint string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		investigationID := chi.URLParam(r, "id")
		if _, ok := s.investigation(investigationID); !ok {
			writeError(w, http.StatusNotFound, "investigation not found")
			return
		}
		runID := s.start(r.Context(), "intel-"+feature, investigationID, nil)
		result, err := s.downstream.intelGET(r.Context(), endpoint, investigationID)
		if err != nil {
			s.fail(r.Context(), runID, "intel-"+feature, investigationID)
			writeError(w, http.StatusBadGateway, "intel failed: "+err.Error())
			return
		}
		s.complete(r.Context(), runID, "intel-"+feature, investigationID, nil)
		writeJSON(w, http.StatusOK, result)
	}
}

func (s *apiServer) intelCapabilities(w http.ResponseWriter, r *http.Request) {
	result, err := s.downstream.intelGET(r.Context(), "/v1/capabilities", "")
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func strAny(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	default:
		return ""
	}
}
