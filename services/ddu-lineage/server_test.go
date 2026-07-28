package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestLineageProxyForwardsAndFiltersRuns(t *testing.T) {
	var forwarded []byte
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/lineage":
			forwarded, _ = io.ReadAll(r.Body)
			w.WriteHeader(http.StatusCreated)
		case "/api/v1/namespaces":
			_ = json.NewEncoder(w).Encode(map[string]any{"namespaces": []any{}})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	handler := newHandler(backend.URL, backend.Client())
	event := []byte(`{
		"eventType":"COMPLETE",
		"eventTime":"2026-07-22T00:00:00Z",
		"run":{"runId":"run-1","facets":{"dduInvestigation":{"investigation_id":"case-001"}}},
		"job":{"namespace":"ddu.dev","name":"ddu-vision:detect","facets":{}},
		"inputs":[],
		"outputs":[],
		"producer":"https://ddu.local/ddu-vision/0.0.1"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/events", bytes.NewReader(event))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("POST status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if !bytes.Equal(forwarded, event) {
		t.Fatalf("forwarded event = %s", forwarded)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/runs?investigation_id=case-001", nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var response RunsResponse
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if len(response.Runs) != 1 || response.Runs[0].RunID != "run-1" {
		t.Fatalf("runs = %+v", response.Runs)
	}
}
