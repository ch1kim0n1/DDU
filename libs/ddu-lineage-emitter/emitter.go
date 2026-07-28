// Package lineageemitter wraps the OpenLineage HTTP transport so that every
// ddu-* service can emit RunEvents with a single call. Events are sent to the
// OpenLineage backend (Marquez in dev) configured via OPENLINEAGE_URL.
//
// The emitter is non-blocking: failed sends are logged but never panic the
// caller. Provenance is more important than perfect delivery, but we retry
// once on transient failure.
package lineageemitter

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Client emits OpenLineage events to a backend (Marquez, Spline, etc.).
type Client struct {
	url       string
	namespace string
	httpc     *http.Client
	producer  Producer
}

// Producer identifies the service emitting the event. Populated from ServiceVersion.
type Producer struct {
	Service        string `json:"service"`
	ServiceVersion string `json:"serviceVersion"`
	Tool           string `json:"tool"`
	ToolVersion    string `json:"toolVersion"`
	Model          string `json:"model,omitempty"`
	ModelVersion   string `json:"modelVersion,omitempty"`
	GitCommit      string `json:"gitCommit,omitempty"`
}

// Input describes a consumed DDU artifact (evidence, entity, observation).
type Input struct {
	Namespace string            `json:"namespace"`
	Name      string            `json:"name"`
	Type      string            `json:"type"`
	Facets    map[string]string `json:"facets,omitempty"`
}

// Output describes a produced DDU artifact.
type Output struct {
	Namespace string            `json:"namespace"`
	Name      string            `json:"name"`
	Type      string            `json:"type"`
	Facets    map[string]string `json:"facets,omitempty"`
}

// Event is the high-level payload callers construct. The emitter translates
// it to the OpenLineage RunEvent schema.
type Event struct {
	EventType string            `json:"eventType"` // START, RUNNING, COMPLETE, FAIL, ABORT
	RunID     string            `json:"runId"`
	JobName   string            `json:"jobName"`
	Inputs    []Input           `json:"inputs,omitempty"`
	Outputs   []Output          `json:"outputs,omitempty"`
	Facets    map[string]string `json:"facets,omitempty"`
}

// New returns a Client configured from environment variables:
//
//	OPENLINEAGE_URL       — backend URL (required)
//	OPENLINEAGE_NAMESPACE — job namespace, defaults to "ddu.dev"
//	OPENLINEAGE_TIMEOUT   — HTTP timeout, defaults to 5s
func New(producer Producer) (*Client, error) {
	url := strings.TrimRight(os.Getenv("OPENLINEAGE_URL"), "/")
	if url == "" {
		return nil, fmt.Errorf("lineageemitter: OPENLINEAGE_URL not set")
	}
	ns := os.Getenv("OPENLINEAGE_NAMESPACE")
	if ns == "" {
		ns = "ddu.dev"
	}
	timeout := 5 * time.Second
	if t := os.Getenv("OPENLINEAGE_TIMEOUT"); t != "" {
		if d, err := time.ParseDuration(t); err == nil {
			timeout = d
		}
	}
	return &Client{
		url:       url + "/api/v1/lineage",
		namespace: ns,
		httpc:     &http.Client{Timeout: timeout},
		producer:  producer,
	}, nil
}

// NewRunID returns a fresh UUID for a new run. Convenience helper.
func NewRunID() string { return uuid.NewString() }

// Emit sends a RunEvent to the OpenLineage backend. Safe to call from any
// goroutine. Returns nil on success or on backend unavailability (logged only).
func (c *Client) Emit(ctx context.Context, e Event) error {
	if e.RunID == "" {
		e.RunID = NewRunID()
	}
	payload := c.buildPayload(e)
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("lineageemitter: marshal: %w", err)
	}
	if err := c.send(ctx, body); err != nil {
		// One retry after a short backoff. Provenance is important.
		select {
		case <-time.After(500 * time.Millisecond):
		case <-ctx.Done():
			return ctx.Err()
		}
		if err2 := c.send(ctx, body); err2 != nil {
			return fmt.Errorf("lineageemitter: send failed (retry): %w (first: %v)", err2, err)
		}
	}
	return nil
}

// MustEmit wraps Emit and logs on error instead of returning. Use only when
// the caller cannot act on the error and wants fire-and-forget semantics.
func (c *Client) MustEmit(ctx context.Context, e Event) {
	if err := c.Emit(ctx, e); err != nil {
		fmt.Fprintf(os.Stderr, "lineageemitter: emit failed: %v\n", err)
	}
}

func (c *Client) send(ctx context.Context, body []byte) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("openlineage returned %d: %s", resp.StatusCode, string(b))
	}
	return nil
}

func (c *Client) buildPayload(e Event) map[string]any {
	now := time.Now().UTC().Format(time.RFC3339Nano)
	run := map[string]any{
		"runId":  e.RunID,
		"facets": map[string]any{},
	}
	if e.Facets != nil {
		// Convert string facets to JSON-parsed values when possible.
		parsed := make(map[string]any, len(e.Facets))
		for k, v := range e.Facets {
			var j any
			if err := json.Unmarshal([]byte(v), &j); err == nil {
				parsed[k] = j
			} else {
				parsed[k] = v
			}
		}
		run["facets"] = parsed
	}
	job := map[string]any{
		"namespace": c.namespace,
		"name":      e.JobName,
		"facets": map[string]any{
			"dduProducer": c.producer,
		},
	}
	inputs := make([]map[string]any, 0, len(e.Inputs))
	for _, in := range e.Inputs {
		inputs = append(inputs, map[string]any{
			"namespace": in.Namespace,
			"name":      in.Name,
			"facets": map[string]any{
				"dataType": in.Type,
			},
		})
	}
	outputs := make([]map[string]any, 0, len(e.Outputs))
	for _, out := range e.Outputs {
		outputs = append(outputs, map[string]any{
			"namespace": out.Namespace,
			"name":      out.Name,
			"facets": map[string]any{
				"dataType": out.Type,
			},
		})
	}
	return map[string]any{
		"eventType": strings.ToUpper(e.EventType),
		"eventTime": now,
		"run":       run,
		"job":       job,
		"inputs":    inputs,
		"outputs":   outputs,
		"producer":  c.producerURI(),
	}
}

func (c *Client) producerURI() string {
	service := c.producer.Service
	if service == "" {
		service = "unknown"
	}
	version := c.producer.ServiceVersion
	if version == "" {
		version = "unknown"
	}
	return fmt.Sprintf("https://ddu.local/%s/%s", url.PathEscape(service), url.PathEscape(version))
}
