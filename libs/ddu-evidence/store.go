// Package evidence provides content-addressed storage for DDU evidence
// objects in any S3-compatible store (MinIO in dev). Evidence is immutable:
// the same content always produces the same id (sha256 hash) and is stored
// at a deterministic path.
//
// Object key layout:
//
//	ddu-evidence/<investigation_id>/<sha256_hex>
//
// Bucket is configurable; defaults to "ddu-evidence".
package evidence

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"mime"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Default bucket names. Match docker-compose minio-init.
const (
	DefaultEvidenceBucket = "ddu-evidence"
	DefaultModelsBucket   = "ddu-models"
	DefaultWARCsBucket    = "ddu-warcs"
	DefaultFramesBucket   = "ddu-frames"
)

// Store is an S3-compatible evidence store. Construct with New.
type Store struct {
	s3       *s3.Client
	bucket   string
	endpoint string // for presigned URLs / debugging
}

// Options for constructing a Store.
type Options struct {
	Endpoint        string // e.g. http://localhost:9000
	Region          string // e.g. us-east-1 (MinIO ignores but requires)
	AccessKeyID     string
	SecretAccessKey string
	Bucket          string // defaults to DefaultEvidenceBucket
	UsePathStyle    bool   // true for MinIO
}

// New constructs an evidence Store backed by an S3-compatible service.
// Credentials may come from Options or from the default AWS credential chain.
func New(ctx context.Context, opts Options) (*Store, error) {
	if opts.Bucket == "" {
		opts.Bucket = DefaultEvidenceBucket
	}
	if opts.Region == "" {
		opts.Region = "us-east-1"
	}
	var creds aws.CredentialsProvider
	if opts.AccessKeyID != "" && opts.SecretAccessKey != "" {
		creds = credentials.NewStaticCredentialsProvider(opts.AccessKeyID, opts.SecretAccessKey, "")
	}
	cfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion(opts.Region),
		config.WithCredentialsProvider(creds),
	)
	if err != nil {
		return nil, fmt.Errorf("evidence: load aws config: %w", err)
	}
	s3c := s3.NewFromConfig(cfg, func(o *s3.Options) {
		if opts.Endpoint != "" {
			o.BaseEndpoint = aws.String(opts.Endpoint)
		}
		o.UsePathStyle = opts.UsePathStyle
	})
	return &Store{
		s3:       s3c,
		bucket:   opts.Bucket,
		endpoint: opts.Endpoint,
	}, nil
}

// Ping verifies that the configured evidence bucket is reachable.
func (s *Store) Ping(ctx context.Context) error {
	if _, err := s.s3.HeadBucket(ctx, &s3.HeadBucketInput{
		Bucket: aws.String(s.bucket),
	}); err != nil {
		return fmt.Errorf("evidence: head bucket: %w", err)
	}
	return nil
}

// Hash returns the sha256 hex digest of the supplied content.
// Use this to compute an evidence id without storing.
func Hash(r io.Reader) (string, error) {
	h := sha256.New()
	if _, err := io.Copy(h, r); err != nil {
		return "", err
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
}

// ObjectKey returns the deterministic S3 object key for an evidence id within
// an investigation.
func ObjectKey(investigationID, id string) string {
	// Strip the "sha256:" prefix to keep keys shorter; the prefix is preserved
	// in the Evidence.Id field.
	hex := strings.TrimPrefix(id, "sha256:")
	return path.Join(investigationID, hex)
}

// MetadataObjectKey returns the immutable JSON sidecar key for an Evidence record.
func MetadataObjectKey(investigationID, id string) string {
	hex := strings.TrimPrefix(id, "sha256:")
	return path.Join(investigationID, ".ddu", "metadata", hex+".json")
}

// Put stores content under <bucket>/<investigationID>/<sha256>. Returns the
// evidence id. If the object already exists, it is left untouched (immutable).
// mimeType is required; if empty, application/octet-stream is used.
func (s *Store) Put(ctx context.Context, investigationID string, r io.Reader, mimeType string) (string, error) {
	if investigationID == "" {
		return "", errors.New("evidence: investigationID required")
	}
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}
	// We need the hash and the bytes. Tee through a hasher while uploading.
	h := sha256.New()
	tee := io.TeeReader(r, h)

	// We must compute the id before PutObject, but we don't want to buffer
	// the whole file. Strategy: read once to compute hash + size into a
	// temp buffer is not great for large files. Instead, do a two-pass:
	//   1. Compute hash by reading (caller's reader).
	//   2. Re-open / seek if possible.
	// For simplicity in the MVP, we buffer via io.ReadAll. Evidence sizes
	// are bounded by MinIO's 5TB object limit but in practice we expect
	// images, frames, WARCs — typically <1GB. A streaming version can be
	// added later using multipart upload with a known key.
	buf, err := io.ReadAll(tee)
	if err != nil {
		return "", fmt.Errorf("evidence: read content: %w", err)
	}
	id := "sha256:" + hex.EncodeToString(h.Sum(nil))
	key := ObjectKey(investigationID, id)

	// Check if exists; if so, skip upload (idempotent).
	if exists, err := s.exists(ctx, key); err != nil {
		return "", fmt.Errorf("evidence: head object: %w", err)
	} else if exists {
		return id, nil
	}

	if _, err := s.s3.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(s.bucket),
		Key:         aws.String(key),
		Body:        bytesReader(buf),
		ContentType: aws.String(mimeType),
	}); err != nil {
		return "", fmt.Errorf("evidence: put object: %w", err)
	}
	return id, nil
}

// Get returns a reader for the stored evidence object. Caller must close it.
func (s *Store) Get(ctx context.Context, investigationID, id string) (io.ReadCloser, string, error) {
	key := ObjectKey(investigationID, id)
	out, err := s.s3.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return nil, "", fmt.Errorf("evidence: get object: %w", err)
	}
	ct := ""
	if out.ContentType != nil {
		ct = *out.ContentType
	}
	return out.Body, ct, nil
}

// PutMetadata stores an immutable JSON sidecar for an Evidence record.
func (s *Store) PutMetadata(ctx context.Context, investigationID, id string, data []byte) error {
	if investigationID == "" || id == "" {
		return errors.New("evidence: investigationID and id required")
	}
	key := MetadataObjectKey(investigationID, id)
	if exists, err := s.exists(ctx, key); err != nil {
		return fmt.Errorf("evidence: head metadata: %w", err)
	} else if exists {
		return nil
	}
	_, err := s.s3.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(s.bucket),
		Key:         aws.String(key),
		Body:        bytesReader(data),
		ContentType: aws.String("application/json"),
	})
	if err != nil {
		return fmt.Errorf("evidence: put metadata: %w", err)
	}
	return nil
}

// GetMetadata returns the JSON sidecar for an Evidence record.
func (s *Store) GetMetadata(ctx context.Context, investigationID, id string) ([]byte, error) {
	out, err := s.s3.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(MetadataObjectKey(investigationID, id)),
	})
	if err != nil {
		return nil, fmt.Errorf("evidence: get metadata: %w", err)
	}
	defer out.Body.Close()
	data, err := io.ReadAll(out.Body)
	if err != nil {
		return nil, fmt.Errorf("evidence: read metadata: %w", err)
	}
	return data, nil
}

// ListMetadata returns all Evidence JSON sidecars for an investigation.
func (s *Store) ListMetadata(ctx context.Context, investigationID string) ([][]byte, error) {
	if investigationID == "" {
		return nil, errors.New("evidence: investigationID required")
	}
	prefix := path.Join(investigationID, ".ddu", "metadata") + "/"
	paginator := s3.NewListObjectsV2Paginator(s.s3, &s3.ListObjectsV2Input{
		Bucket: aws.String(s.bucket),
		Prefix: aws.String(prefix),
	})
	var keys []string
	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("evidence: list metadata: %w", err)
		}
		for _, object := range page.Contents {
			if object.Key != nil {
				keys = append(keys, *object.Key)
			}
		}
	}
	sort.Strings(keys)
	records := make([][]byte, 0, len(keys))
	for _, key := range keys {
		out, err := s.s3.GetObject(ctx, &s3.GetObjectInput{
			Bucket: aws.String(s.bucket),
			Key:    aws.String(key),
		})
		if err != nil {
			return nil, fmt.Errorf("evidence: get listed metadata: %w", err)
		}
		data, readErr := io.ReadAll(out.Body)
		closeErr := out.Body.Close()
		if readErr != nil {
			return nil, fmt.Errorf("evidence: read listed metadata: %w", readErr)
		}
		if closeErr != nil {
			return nil, fmt.Errorf("evidence: close listed metadata: %w", closeErr)
		}
		records = append(records, data)
	}
	return records, nil
}

// PresignGet returns a temporary URL for downloading an Evidence object.
func (s *Store) PresignGet(ctx context.Context, investigationID, id string, expires time.Duration) (string, error) {
	if expires <= 0 {
		expires = 15 * time.Minute
	}
	out, err := s3.NewPresignClient(s.s3).PresignGetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(ObjectKey(investigationID, id)),
	}, func(opts *s3.PresignOptions) {
		opts.Expires = expires
	})
	if err != nil {
		return "", fmt.Errorf("evidence: presign get: %w", err)
	}
	return out.URL, nil
}

// Head returns metadata about a stored evidence object without downloading it.
type Meta struct {
	ID           string
	Size         int64
	MimeType     string
	LastModified time.Time
}

func (s *Store) Head(ctx context.Context, investigationID, id string) (Meta, error) {
	key := ObjectKey(investigationID, id)
	out, err := s.s3.HeadObject(ctx, &s3.HeadObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return Meta{}, fmt.Errorf("evidence: head object: %w", err)
	}
	m := Meta{ID: id}
	if out.ContentLength != nil {
		m.Size = *out.ContentLength
	}
	if out.ContentType != nil {
		m.MimeType = *out.ContentType
	}
	if out.LastModified != nil {
		m.LastModified = *out.LastModified
	}
	return m, nil
}

// URI returns the canonical s3:// URI for an evidence id.
func (s *Store) URI(investigationID, id string) string {
	return fmt.Sprintf("s3://%s/%s", s.bucket, ObjectKey(investigationID, id))
}

// GuessMimeType infers a MIME type from a filename. Returns
// application/octet-stream if unknown.
func GuessMimeType(filename string) string {
	ct := mime.TypeByExtension(path.Ext(filename))
	if ct == "" {
		return "application/octet-stream"
	}
	return ct
}

func (s *Store) exists(ctx context.Context, key string) (bool, error) {
	_, err := s.s3.HeadObject(ctx, &s3.HeadObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		var nf interface{ ErrorCode() string }
		if errors.As(err, &nf) && nf.ErrorCode() == "NotFound" {
			return false, nil
		}
		// MinIO / S3 return "NotFound" or "NoSuchKey" depending on version.
		if strings.Contains(err.Error(), "NotFound") || strings.Contains(err.Error(), "NoSuchKey") {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// bytesReader avoids importing bytes here for callers; small helper.
type bytesReaderImpl struct {
	b   []byte
	pos int
}

func bytesReader(b []byte) io.ReadSeeker { return &bytesReaderImpl{b: b} }

func (r *bytesReaderImpl) Read(p []byte) (int, error) {
	if r.pos >= len(r.b) {
		return 0, io.EOF
	}
	n := copy(p, r.b[r.pos:])
	r.pos += n
	return n, nil
}

func (r *bytesReaderImpl) Seek(offset int64, whence int) (int64, error) {
	var abs int64
	switch whence {
	case io.SeekStart:
		abs = offset
	case io.SeekCurrent:
		abs = int64(r.pos) + offset
	case io.SeekEnd:
		abs = int64(len(r.b)) + offset
	}
	if abs < 0 || abs > int64(len(r.b)) {
		return 0, fmt.Errorf("seek out of range")
	}
	r.pos = int(abs)
	return abs, nil
}
