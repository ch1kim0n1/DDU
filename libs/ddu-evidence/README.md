# ddu-evidence

Go library for content-addressed evidence storage on S3-compatible stores (MinIO in dev).

## Usage

```go
import "github.com/ddu/ddu-evidence"

store, err := evidence.New(ctx, evidence.Options{
    Endpoint:        "http://localhost:9000",
    AccessKeyID:     "dduadmin",
    SecretAccessKey: "ddudevpass",
    UsePathStyle:    true,
})
if err != nil { log.Fatal(err) }

id, err := store.Put(ctx, investigationID, file, "image/jpeg")
// id == "sha256:abc123..."
// Object stored at: s3://ddu-evidence/<investigationID>/abc123...
```

## Layout

Object key: `<investigation_id>/<sha256_hex>` within the configured bucket.

Buckets (created by `minio-init` in docker-compose):
- `ddu-evidence` — original evidence (images, videos, audio, docs, snapshots)
- `ddu-models` — pinned model weights
- `ddu-warcs` — Browsertrix WARC archives
- `ddu-frames` — extracted video frames

## Semantics

- **Immutable.** Same content → same id → same key. Put is idempotent.
- **Content-addressed.** The id IS the sha256 hash. No separate id scheme.
- **Deterministic URI.** `s3://<bucket>/<investigationID>/<sha256_hex>`.
