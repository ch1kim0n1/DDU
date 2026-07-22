package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

type fakeVectorRepository struct {
	collection string
	points     []Point
}

func (f *fakeVectorRepository) Ping(context.Context) error { return nil }
func (f *fakeVectorRepository) Close() error               { return nil }

func (f *fakeVectorRepository) CreateCollection(_ context.Context, name string, _ uint64, _ string) error {
	f.collection = name
	return nil
}

func (f *fakeVectorRepository) Upsert(_ context.Context, _ string, points []Point) error {
	f.points = points
	return nil
}

func (f *fakeVectorRepository) Search(_ context.Context, _ SearchRequest) ([]Match, error) {
	return []Match{{ID: "point-1", Score: 0.95, Payload: map[string]any{"embedding_source": "placeholder"}}}, nil
}

func TestVectorHandlers(t *testing.T) {
	repository := &fakeVectorRepository{}
	handler := newHandler(repository, nil)

	req := httptest.NewRequest(http.MethodPost, "/v1/collections", bytes.NewBufferString(
		`{"name":"images","vector_size":3,"distance":"COSINE"}`,
	))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated || repository.collection != "images" {
		t.Fatalf("collection status = %d, body = %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodPost, "/v1/points/upsert", bytes.NewBufferString(
		`{"collection":"images","points":[{"id":"point-1","vector":[0.1,0.2,0.3],"payload":{"embedding_source":"placeholder"}}]}`,
	))
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || len(repository.points) != 1 {
		t.Fatalf("upsert status = %d, body = %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodPost, "/v1/search", bytes.NewBufferString(
		`{"collection":"images","vector":[0.1,0.2,0.3],"limit":5}`,
	))
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("search status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var response SearchResponse
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if len(response.Matches) != 1 || response.Matches[0].ID != "point-1" {
		t.Fatalf("matches = %+v", response.Matches)
	}
}
