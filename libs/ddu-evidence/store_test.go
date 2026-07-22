package evidence

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"testing"
	"time"
)

func TestMetadataObjectKey(t *testing.T) {
	got := MetadataObjectKey("case-001", "sha256:abcdef")
	want := "case-001/.ddu/metadata/abcdef.json"
	if got != want {
		t.Fatalf("MetadataObjectKey() = %q, want %q", got, want)
	}
}

func TestMetadataLifecycle(t *testing.T) {
	endpoint := os.Getenv("MINIO_TEST_ENDPOINT")
	if endpoint == "" {
		t.Skip("MINIO_TEST_ENDPOINT not set")
	}

	ctx := context.Background()
	store, err := New(ctx, Options{
		Endpoint:        endpoint,
		AccessKeyID:     os.Getenv("MINIO_TEST_ACCESS_KEY"),
		SecretAccessKey: os.Getenv("MINIO_TEST_SECRET_KEY"),
		UsePathStyle:    true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Ping(ctx); err != nil {
		t.Fatal(err)
	}

	investigationID := fmt.Sprintf("test-%d", time.Now().UnixNano())
	id, err := store.Put(ctx, investigationID, strings.NewReader("evidence"), "text/plain")
	if err != nil {
		t.Fatal(err)
	}

	record := []byte(`{"id":"` + id + `","investigation_id":"` + investigationID + `"}`)
	if err := store.PutMetadata(ctx, investigationID, id, record); err != nil {
		t.Fatal(err)
	}

	got, err := store.GetMetadata(ctx, investigationID, id)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, record) {
		t.Fatalf("GetMetadata() = %s, want %s", got, record)
	}

	records, err := store.ListMetadata(ctx, investigationID)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 1 || !bytes.Equal(records[0], record) {
		t.Fatalf("ListMetadata() = %q, want one record %q", records, record)
	}

	url, err := store.PresignGet(ctx, investigationID, id, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(url, strings.TrimPrefix(id, "sha256:")) {
		t.Fatalf("PresignGet() URL %q does not contain evidence key", url)
	}

	body, _, err := store.Get(ctx, investigationID, id)
	if err != nil {
		t.Fatal(err)
	}
	defer body.Close()
	content, err := io.ReadAll(body)
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != "evidence" {
		t.Fatalf("Get() = %q, want evidence", content)
	}
}
