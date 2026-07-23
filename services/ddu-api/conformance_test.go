package main

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func newConformanceBackend(t *testing.T) (*httptest.Server, *conformanceBackendState) {
	t.Helper()
	state := &conformanceBackendState{mu: sync.Mutex{}}
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state.record(r)
		switch {
		case r.URL.Path == "/v1/ingest/image":
			_ = json.NewEncoder(w).Encode(Evidence{
				ID: "sha256:conf", InvestigationID: r.Header.Get("X-Investigation-Id"),
				MimeType: "image/jpeg", Metadata: map[string]string{},
			})
		case r.URL.Path == "/v1/detect":
			_ = json.NewEncoder(w).Encode([]Observation{{
				ID: "obs-conf-1", InvestigationID: "case", EvidenceID: "sha256:conf",
				Type: "OBSERVATION_TYPE_OBJECT", Label: "vehicle", DetectorConfidence: 0.8,
				Attributes: map[string]string{"epistemic_class": "EPISTEMIC_CLASS_OBSERVATION"},
				Provenance: map[string]any{"produced_by_service": "ddu-vision", "model_version": "0.4.0"},
			}})
		case r.URL.Path == "/v1/ocr" || r.URL.Path == "/v1/locate":
			_ = json.NewEncoder(w).Encode([]Observation{})
		case r.URL.Path == "/v1/entities" && r.Method == http.MethodPost:
			var entity Entity
			_ = json.NewDecoder(r.Body).Decode(&entity)
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(entity)
		case r.URL.Path == "/v1/entities":
			_ = json.NewEncoder(w).Encode(EntityList{Entities: []Entity{}})
		case r.URL.Path == "/v1/relationships":
			_ = json.NewEncoder(w).Encode(RelationshipList{Relationships: []Relationship{}})
		case r.URL.Path == "/v1/evidence":
			_ = json.NewEncoder(w).Encode(map[string]any{"evidence": []Evidence{}})
		case r.URL.Path == "/v1/runs":
			_ = json.NewEncoder(w).Encode(RunsResponse{Runs: []map[string]any{}, Count: 0})
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	return backend, state
}

type conformanceBackendState struct {
	mu       sync.Mutex
	requests []string
}

func (s *conformanceBackendState) record(r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.requests = append(s.requests, r.Method+" "+r.URL.Path)
}

func (s *conformanceBackendState) snapshot() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.requests))
	copy(out, s.requests)
	return out
}

func TestConformanceHealthzState(t *testing.T) {
	backend, _ := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("healthz status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	state, ok := body["state"].(string)
	if !ok {
		t.Fatalf("state missing or not a string: %v", body["state"])
	}
	switch state {
	case "HEALTHY", "DEGRADED", "UNHEALTHY":
	default:
		t.Fatalf("state = %s, want one of HEALTHY|DEGRADED|UNHEALTHY", state)
	}
}

func TestConformanceVersionzFields(t *testing.T) {
	backend, _ := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	req := httptest.NewRequest(http.MethodGet, "/versionz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("versionz status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	required := []string{
		"service", "service_version", "tool", "tool_version",
		"git_commit", "built_at",
	}
	for _, field := range required {
		value, ok := body[field]
		if !ok {
			t.Fatalf("versionz missing required field %q: %v", field, body)
		}
		if s, isString := value.(string); isString && s == "" {
			t.Fatalf("versionz field %q is empty", field)
		}
	}
}

func TestConformanceObservationProvenance(t *testing.T) {
	backend, _ := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(createRec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	file, _ := writer.CreateFormFile("file", "image.jpg")
	_, _ = file.Write([]byte{0xff, 0xd8, 0xff, 0xd9})
	_ = writer.Close()
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/images",
		body,
	)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("workflow status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var result WorkflowResult
	if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	if len(result.Observations) == 0 {
		t.Fatal("no observations returned")
	}
	for i, observation := range result.Observations {
		if observation.Provenance == nil || len(observation.Provenance) == 0 {
			t.Fatalf("observation[%d] %s missing provenance block", i, observation.ID)
		}
	}
}

func TestConformanceObservationEpistemicClass(t *testing.T) {
	backend, _ := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(createRec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	file, _ := writer.CreateFormFile("file", "image.jpg")
	_, _ = file.Write([]byte{0xff, 0xd8, 0xff, 0xd9})
	_ = writer.Close()
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/images",
		body,
	)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("workflow status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var result WorkflowResult
	if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	if len(result.Observations) == 0 {
		t.Fatal("no observations returned")
	}
	for i, observation := range result.Observations {
		if observation.Attributes == nil {
			t.Fatalf("observation[%d] %s missing attributes", i, observation.ID)
		}
		if observation.Attributes["epistemic_class"] == "" {
			t.Fatalf("observation[%d] %s missing epistemic_class in attributes", i, observation.ID)
		}
	}
}

func TestConformanceEntityProvenance(t *testing.T) {
	backend, _ := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(createRec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	file, _ := writer.CreateFormFile("file", "image.jpg")
	_, _ = file.Write([]byte{0xff, 0xd8, 0xff, 0xd9})
	_ = writer.Close()
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/images",
		body,
	)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("workflow status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var result WorkflowResult
	if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	if len(result.Entities) == 0 {
		t.Fatal("no entities returned")
	}
	for i, entity := range result.Entities {
		if entity.Provenance == nil || len(entity.Provenance) == 0 {
			t.Fatalf("entity[%d] %s missing provenance", i, entity.ID)
		}
	}
}

func TestConformanceNoDirectBackendBypass(t *testing.T) {
	backend, state := newConformanceBackend(t)
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, backend.Client(), nil)

	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(createRec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	for _, target := range []string{
		"/v1/investigations/" + investigation.ID + "/entities",
		"/v1/investigations/" + investigation.ID + "/observations",
		"/v1/investigations/" + investigation.ID + "/relationships",
		"/v1/investigations/" + investigation.ID + "/lineage",
		"/v1/investigations/" + investigation.ID + "/evidence",
	} {
		req := httptest.NewRequest(http.MethodGet, target, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("GET %s status = %d, body = %s", target, rec.Code, rec.Body.String())
		}
	}

	requests := state.snapshot()
	if len(requests) == 0 {
		t.Fatal("no proxied backend requests recorded; API layer bypassed downstream client")
	}
	allowedPaths := map[string]bool{
		"/v1/entities":      true,
		"/v1/relationships": true,
		"/v1/runs":          true,
		"/v1/evidence":      true,
		"/healthz":          true,
	}
	for _, entry := range requests {
		parts := strings.SplitN(entry, " ", 2)
		if len(parts) != 2 {
			t.Fatalf("malformed backend request entry %q", entry)
		}
		if !allowedPaths[parts[1]] {
			t.Fatalf("unexpected backend request %q (API layer bypassed service contract)", entry)
		}
	}
}
