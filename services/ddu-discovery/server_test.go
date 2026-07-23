package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestDiscoverStubReturnsObservations(t *testing.T) {
	os.Setenv("MODEL_MODE", "stub")
	defer os.Unsetenv("MODEL_MODE")

	handler := newHandler(nil)
	body := []byte(`{"username":"testuser","investigation_id":"case-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/discover", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("discover status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var response DiscoverResponse
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if len(response.Observations) == 0 {
		t.Fatal("expected observations in stub mode")
	}
	obs := response.Observations[0]
	if obs.Type != "OBSERVATION_TYPE_USERNAME" {
		t.Fatalf("observation type = %q", obs.Type)
	}
	if obs.Attributes["epistemic_class"] != "EPISTEMIC_CLASS_OBSERVATION" {
		t.Fatalf("epistemic_class = %q", obs.Attributes["epistemic_class"])
	}
	if obs.Provenance.ProducedByService != "ddu-discovery" {
		t.Fatalf("produced_by_service = %q", obs.Provenance.ProducedByService)
	}
	if obs.Provenance.Tool != "sherlock" || obs.Provenance.ToolVersion != "0.14.0" {
		t.Fatalf("provenance tool = %q version = %q", obs.Provenance.Tool, obs.Provenance.ToolVersion)
	}
	if obs.EvidenceID != "testuser" {
		t.Fatalf("evidence_id = %q", obs.EvidenceID)
	}
}

func TestDiscoverRequiresUsernameAndInvestigationID(t *testing.T) {
	handler := newHandler(nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/discover", bytes.NewBufferString(`{"username":"testuser"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("missing investigation_id status = %d", rec.Code)
	}
}
