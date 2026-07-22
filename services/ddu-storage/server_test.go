package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	evidence "github.com/ddu/ddu-evidence"
	lineageemitter "github.com/ddu/ddu-lineage-emitter"
)

type fakeEvidenceStore struct {
	content  []byte
	metadata []byte
}

func (f *fakeEvidenceStore) Put(_ context.Context, _ string, r io.Reader, _ string) (string, error) {
	var err error
	f.content, err = io.ReadAll(r)
	return "sha256:abc123", err
}

func (f *fakeEvidenceStore) Head(_ context.Context, _, id string) (evidence.Meta, error) {
	return evidence.Meta{ID: id, Size: int64(len(f.content)), MimeType: "image/jpeg"}, nil
}

func (f *fakeEvidenceStore) URI(investigationID, id string) string {
	return "s3://ddu-evidence/" + investigationID + "/" + strings.TrimPrefix(id, "sha256:")
}

func (f *fakeEvidenceStore) PutMetadata(_ context.Context, _, _ string, data []byte) error {
	f.metadata = append([]byte(nil), data...)
	return nil
}

func (f *fakeEvidenceStore) GetMetadata(_ context.Context, _, _ string) ([]byte, error) {
	return append([]byte(nil), f.metadata...), nil
}

func (f *fakeEvidenceStore) ListMetadata(_ context.Context, _ string) ([][]byte, error) {
	return [][]byte{append([]byte(nil), f.metadata...)}, nil
}

func (f *fakeEvidenceStore) PresignGet(_ context.Context, _, _ string, _ time.Duration) (string, error) {
	return "http://minio.test/presigned", nil
}

func (f *fakeEvidenceStore) Ping(_ context.Context) error {
	return nil
}

type fakeLineageEmitter struct {
	events []lineageemitter.Event
}

func (f *fakeLineageEmitter) Emit(_ context.Context, event lineageemitter.Event) error {
	f.events = append(f.events, event)
	return nil
}

func TestEvidenceUploadGetAndList(t *testing.T) {
	store := &fakeEvidenceStore{}
	lineage := &fakeLineageEmitter{}
	handler := newHandler(store, lineage)

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("content", "photo.jpg")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write([]byte("jpeg-content")); err != nil {
		t.Fatal(err)
	}
	if err := writer.WriteField("metadata", `{"camera_make":"DDU"}`); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/evidence", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Investigation-Id", "case-001")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("POST status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var uploaded Evidence
	if err := json.NewDecoder(rec.Body).Decode(&uploaded); err != nil {
		t.Fatal(err)
	}
	if uploaded.ID != "sha256:abc123" {
		t.Fatalf("id = %q", uploaded.ID)
	}
	if uploaded.InvestigationID != "case-001" || uploaded.Type != "EVIDENCE_TYPE_IMAGE" {
		t.Fatalf("unexpected evidence: %+v", uploaded)
	}
	if uploaded.AcquisitionMethod != "user-upload" || !uploaded.IsOriginal {
		t.Fatalf("unexpected acquisition fields: %+v", uploaded)
	}
	if uploaded.Metadata["camera_make"] != "DDU" {
		t.Fatalf("metadata = %#v", uploaded.Metadata)
	}
	if len(lineage.events) != 2 || lineage.events[0].EventType != "START" || lineage.events[1].EventType != "COMPLETE" {
		t.Fatalf("lineage events = %#v", lineage.events)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/evidence/sha256:abc123?investigation_id=case-001", nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("GET status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var fetched EvidenceResponse
	if err := json.NewDecoder(rec.Body).Decode(&fetched); err != nil {
		t.Fatal(err)
	}
	if fetched.DownloadURL != "http://minio.test/presigned" || fetched.Evidence.ID != uploaded.ID {
		t.Fatalf("GET response = %+v", fetched)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/evidence?investigation_id=case-001", nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("LIST status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var listed EvidenceList
	if err := json.NewDecoder(rec.Body).Decode(&listed); err != nil {
		t.Fatal(err)
	}
	if len(listed.Evidence) != 1 || listed.Evidence[0].ID != uploaded.ID {
		t.Fatalf("LIST response = %+v", listed)
	}
}

func TestEvidenceUploadRequiresInvestigation(t *testing.T) {
	handler := newHandler(&fakeEvidenceStore{}, &fakeLineageEmitter{})
	req := httptest.NewRequest(http.MethodPost, "/v1/evidence", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusBadRequest)
	}
}
