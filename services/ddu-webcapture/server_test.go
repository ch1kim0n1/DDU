package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

type fakeStorageClient struct {
	content         []byte
	investigationID string
	mimeType        string
	originURI       string
}

func (f *fakeStorageClient) Ping(context.Context) error { return nil }

func (f *fakeStorageClient) Store(
	_ context.Context,
	investigationID, _, mimeType string,
	content []byte,
	_ map[string]string,
	originURI, _, _ string,
) (Evidence, error) {
	f.content = content
	f.investigationID = investigationID
	f.mimeType = mimeType
	f.originURI = originURI
	return Evidence{
		ID:              "sha256:test",
		InvestigationID: investigationID,
		MimeType:        mimeType,
		Metadata:        map[string]string{},
		IsOriginal:      true,
	}, nil
}

func TestCaptureStubReturnsWARCEvidence(t *testing.T) {
	os.Setenv("MODEL_MODE", "stub")
	defer os.Unsetenv("MODEL_MODE")

	storage := &fakeStorageClient{}
	handler := newHandler(storage, nil, http.DefaultClient)
	body := []byte(`{"url":"https://example.com","investigation_id":"case-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/capture", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("capture status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var response CaptureResponse
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response.Evidence.Type != "EVIDENCE_TYPE_WEB_SNAPSHOT" {
		t.Fatalf("evidence type = %q", response.Evidence.Type)
	}
	if storage.mimeType != "application/warc+gzip" {
		t.Fatalf("stored mime = %q", storage.mimeType)
	}
	if storage.originURI != "https://example.com" {
		t.Fatalf("stored origin = %q", storage.originURI)
	}
	if len(storage.content) == 0 {
		t.Fatal("expected stored WARC content")
	}
}

func TestCaptureRequiresURLAndInvestigationID(t *testing.T) {
	handler := newHandler(&fakeStorageClient{}, nil, http.DefaultClient)
	req := httptest.NewRequest(http.MethodPost, "/v1/capture", bytes.NewBufferString(`{"url":"https://example.com"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("missing investigation_id status = %d", rec.Code)
	}
}

func TestCaptureRejectsInvalidURL(t *testing.T) {
	handler := newHandler(&fakeStorageClient{}, nil, http.DefaultClient)
	req := httptest.NewRequest(http.MethodPost, "/v1/capture", bytes.NewBufferString(`{"url":"not-a-url","investigation_id":"case-1"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("invalid url status = %d", rec.Code)
	}
}
