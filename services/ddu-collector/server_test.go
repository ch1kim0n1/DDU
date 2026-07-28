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
	storeCount      int
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
	f.storeCount++
	return Evidence{
		ID:              "sha256:test",
		InvestigationID: investigationID,
		MimeType:        mimeType,
		Metadata:        map[string]string{},
		IsOriginal:      true,
	}, nil
}

func TestCollectStubDownloadsAndStoresEvidence(t *testing.T) {
	os.Setenv("MODEL_MODE", "stub")
	defer os.Unsetenv("MODEL_MODE")

	storage := &fakeStorageClient{}
	handler := newHandler(storage, nil, http.DefaultClient)
	body := []byte(`{"url":"https://example.com/gallery","investigation_id":"case-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/collect", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("collect status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var response CollectResponse
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if len(response.Evidence) == 0 {
		t.Fatal("expected evidence records in stub mode")
	}
	if storage.investigationID != "case-1" || storage.mimeType != "image/jpeg" {
		t.Fatalf("stored investigation=%q mime=%q", storage.investigationID, storage.mimeType)
	}
	if storage.originURI != "https://example.com/gallery" {
		t.Fatalf("stored origin=%q", storage.originURI)
	}
}

func TestCollectRequiresURLAndInvestigationID(t *testing.T) {
	handler := newHandler(&fakeStorageClient{}, nil, http.DefaultClient)
	req := httptest.NewRequest(http.MethodPost, "/v1/collect", bytes.NewBufferString(`{"url":"https://example.com"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("missing investigation_id status = %d", rec.Code)
	}
}

func TestCollectRejectsInvalidURL(t *testing.T) {
	handler := newHandler(&fakeStorageClient{}, nil, http.DefaultClient)
	req := httptest.NewRequest(http.MethodPost, "/v1/collect", bytes.NewBufferString(`{"url":"not-a-url","investigation_id":"case-1"}`))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("invalid url status = %d", rec.Code)
	}
}
