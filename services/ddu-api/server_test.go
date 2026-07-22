package main

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
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
	handler := newHandler(config, backend.Client(), nil)

	req := httptest.NewRequest(http.MethodPost, "/v1/investigations", bytes.NewBufferString(`{"name":"Case One"}`))
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
