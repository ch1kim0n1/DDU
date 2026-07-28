package main

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	dduhttpclient "github.com/ddu/ddu-httpclient"
)

func TestInvestigationImageWorkflow(t *testing.T) {
	var mu sync.Mutex
	entities := []Entity{}
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/ingest/image":
			_ = json.NewEncoder(w).Encode(Evidence{
				ID: "sha256:test", InvestigationID: r.Header.Get("X-Investigation-Id"),
				MimeType: "image/jpeg", Metadata: map[string]string{},
			})
		case r.URL.Path == "/v1/detect":
			_ = json.NewEncoder(w).Encode([]Observation{{
				ID: "observation-1", InvestigationID: "case", EvidenceID: "sha256:test",
				Type: "OBSERVATION_TYPE_OBJECT", Label: "vehicle", DetectorConfidence: 0.8,
				Attributes: map[string]string{"epistemic_class": "EPISTEMIC_CLASS_OBSERVATION"},
				Provenance: map[string]any{"produced_by_service": "ddu-vision", "model_version": "0.4.0"},
			}})
		case r.URL.Path == "/v1/ocr" || r.URL.Path == "/v1/locate":
			_ = json.NewEncoder(w).Encode([]Observation{})
		case r.URL.Path == "/v1/entities" && r.Method == http.MethodPost:
			var entity Entity
			_ = json.NewDecoder(r.Body).Decode(&entity)
			mu.Lock()
			entities = append(entities, entity)
			mu.Unlock()
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(entity)
		case r.URL.Path == "/v1/entities":
			mu.Lock()
			defer mu.Unlock()
			_ = json.NewEncoder(w).Encode(EntityList{Entities: entities})
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)

	req := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(rec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	file, _ := writer.CreateFormFile("file", "image.jpg")
	_, _ = file.Write([]byte{0xff, 0xd8, 0xff, 0xd9})
	_ = writer.Close()
	req = httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/images",
		body,
	)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("workflow status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var result WorkflowResult
	if err := json.NewDecoder(rec.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	if result.EvidenceID != "sha256:test" || len(result.Entities) != 1 {
		t.Fatalf("result = %+v", result)
	}
	if result.Entities[0].Type != "ENTITY_TYPE_OBSERVATION" {
		t.Fatalf("entity type = %s", result.Entities[0].Type)
	}
}

func TestRBACViewerGETAllowed(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)

	req := httptest.NewRequest(http.MethodGet, "/v1/investigations", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET without role header status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestRBACViewerPOSTForbidden(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)

	req := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("POST without role header status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body["error"] != "insufficient role" {
		t.Fatalf("error = %v", body["error"])
	}
	if body["actual"] != RoleViewer {
		t.Fatalf("actual = %v", body["actual"])
	}
}

func TestRBACInvestigatorPOSTAllowed(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)

	req := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	req.Header.Set("X-DDU-Role", RoleInvestigator)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("POST with investigator role status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestIntelHighRiskRequiresAuthorizationPurpose(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()
	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL, Intel: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)
	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Intel"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	var investigation Investigation
	_ = json.NewDecoder(createRec.Body).Decode(&investigation)

	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/intel/household",
		bytes.NewBufferString(`{"subject":"alice"}`),
	)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d body=%s", rec.Code, rec.Body.String())
	}
}

func TestUsernameWorkflow(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/discover":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"observations": []Observation{{
					ID: "obs-user", InvestigationID: "case", EvidenceID: "alice",
					Type: "OBSERVATION_TYPE_USERNAME", Label: "alice",
					Attributes: map[string]string{"platform": "github"},
					Provenance: map[string]any{"produced_by_service": "ddu-discovery"},
				}},
			})
		case r.URL.Path == "/v1/enrich":
			_ = json.NewEncoder(w).Encode([]Observation{})
		case r.URL.Path == "/v1/entities" && r.Method == http.MethodPost:
			var entity Entity
			_ = json.NewDecoder(r.Body).Decode(&entity)
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(entity)
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL, Discovery: backend.URL, OSINT: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)
	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"User Case"}`))
	createReq.Header.Set("X-DDU-Role", RoleAnalyst)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	var investigation Investigation
	_ = json.NewDecoder(createRec.Body).Decode(&investigation)

	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/investigations/"+investigation.ID+"/usernames",
		bytes.NewBufferString(`{"username":"alice"}`),
	)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-DDU-Role", RoleAnalyst)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("username workflow status = %d, body = %s", rec.Code, rec.Body.String())
	}
}

func TestRelationshipsEndpoint(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/relationships" && r.Method == http.MethodGet:
			_ = json.NewEncoder(w).Encode(RelationshipList{Relationships: []Relationship{{
				ID: "rel-1", InvestigationID: "case", SourceEntityID: "e-1",
				TargetEntityID: "e-2", RelationshipType: "RELATIONSHIP_TYPE_CO_OCCURS",
				VerificationState: "VERIFICATION_STATE_VERIFIED",
				Confidence:        Confidence{Value: 0.9},
				EvidenceIDs:       []string{"sha256:test"},
				Provenance:        map[string]any{"produced_by_service": "ddu-graph-store"},
			}}})
		case r.URL.Path == "/healthz":
			_ = json.NewEncoder(w).Encode(map[string]string{"state": "HEALTHY"})
		default:
			http.NotFound(w, r)
		}
	}))
	defer backend.Close()

	config := serviceURLs{
		Ingest: backend.URL, Vision: backend.URL, OCR: backend.URL,
		Geo: backend.URL, GraphStore: backend.URL, Lineage: backend.URL,
		Storage: backend.URL,
	}
	handler := newHandler(config, dduhttpclient.NewClient(dduhttpclient.Config{HTTPClient: backend.Client()}), nil)

	createReq := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
	createReq.Header.Set("X-DDU-Role", RoleAdmin)
	createRec := httptest.NewRecorder()
	handler.ServeHTTP(createRec, createReq)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status = %d, body = %s", createRec.Code, createRec.Body.String())
	}
	var investigation Investigation
	if err := json.NewDecoder(createRec.Body).Decode(&investigation); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/investigations/"+investigation.ID+"/relationships", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("relationships status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var list RelationshipList
	if err := json.NewDecoder(rec.Body).Decode(&list); err != nil {
		t.Fatal(err)
	}
	if len(list.Relationships) != 1 || list.Relationships[0].ID != "rel-1" {
		t.Fatalf("relationships = %+v", list)
	}
}
