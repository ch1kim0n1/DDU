package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"strings"
)

type httpStorageClient struct {
	baseURL string
	client  *http.Client
}

func newStorageClient(baseURL string, client *http.Client) *httpStorageClient {
	return &httpStorageClient{baseURL: strings.TrimRight(baseURL, "/"), client: client}
}

func (c *httpStorageClient) Ping(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/healthz", nil)
	if err != nil {
		return err
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		return fmt.Errorf("storage health returned %s", resp.Status)
	}
	return nil
}

func (c *httpStorageClient) Store(
	ctx context.Context,
	investigationID, filename, mimeType string,
	content []byte,
	metadata map[string]string,
	originURI, acquisitionMethod, originalTimestamp string,
) (Evidence, error) {
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	header := textproto.MIMEHeader{}
	header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="content"; filename=%q`, filename))
	header.Set("Content-Type", mimeType)
	part, err := writer.CreatePart(header)
	if err != nil {
		return Evidence{}, err
	}
	if _, err := part.Write(content); err != nil {
		return Evidence{}, err
	}
	fields := map[string]string{
		"investigation_id":   investigationID,
		"mime_type":          mimeType,
		"origin_uri":         originURI,
		"acquisition_method": acquisitionMethod,
		"original_timestamp": originalTimestamp,
		"acquired_by":        serviceName,
		"is_original":        "true",
	}
	metadataJSON, err := json.Marshal(metadata)
	if err != nil {
		return Evidence{}, err
	}
	fields["metadata"] = string(metadataJSON)
	for key, value := range fields {
		if value != "" {
			if err := writer.WriteField(key, value); err != nil {
				return Evidence{}, err
			}
		}
	}
	if err := writer.Close(); err != nil {
		return Evidence{}, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/evidence", body)
	if err != nil {
		return Evidence{}, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Investigation-Id", investigationID)
	resp, err := c.client.Do(req)
	if err != nil {
		return Evidence{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		detail, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return Evidence{}, fmt.Errorf("storage returned %s: %s", resp.Status, strings.TrimSpace(string(detail)))
	}
	var evidence Evidence
	if err := json.NewDecoder(resp.Body).Decode(&evidence); err != nil {
		return Evidence{}, err
	}
	return evidence, nil
}
