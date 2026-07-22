package main

import (
	"bytes"
	"context"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
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

func TestImageIngestRequiresInvestigationHeaderAndStoresImage(t *testing.T) {
	storage := &fakeStorageClient{}
	handler := newHandler(storage, nil, http.DefaultClient)

	body, contentType := imageUpload(t)
	req := httptest.NewRequest(http.MethodPost, "/v1/ingest/image", body)
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("missing header status = %d", rec.Code)
	}

	body, contentType = imageUpload(t)
	req = httptest.NewRequest(http.MethodPost, "/v1/ingest/image", body)
	req.Header.Set("Content-Type", contentType)
	req.Header.Set("X-Investigation-Id", "case-1")
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("image status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if storage.investigationID != "case-1" || storage.mimeType != "image/jpeg" {
		t.Fatalf("stored investigation=%q mime=%q", storage.investigationID, storage.mimeType)
	}
}

func TestURLIngestFetchesAndStoresContent(t *testing.T) {
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "image/png")
		_, _ = w.Write([]byte("\x89PNG\r\n\x1a\n"))
	}))
	defer source.Close()

	storage := &fakeStorageClient{}
	handler := newHandler(storage, nil, source.Client())
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/ingest/url",
		bytes.NewBufferString(`{"url":"`+source.URL+`/image.png"}`),
	)
	req.Header.Set("X-Investigation-Id", "case-2")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("URL status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if storage.originURI != source.URL+"/image.png" || storage.mimeType != "image/png" {
		t.Fatalf("stored origin=%q mime=%q", storage.originURI, storage.mimeType)
	}
	if len(storage.content) == 0 {
		t.Fatal("expected stored content")
	}
}

func imageUpload(t *testing.T) (*bytes.Buffer, string) {
	t.Helper()
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	file, err := writer.CreateFormFile("file", "sample.jpg")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.Write([]byte{0xff, 0xd8, 0xff, 0xd9}); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return body, writer.FormDataContentType()
}
