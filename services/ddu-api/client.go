package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

type serviceURLs struct {
	Ingest     string
	Vision     string
	OCR        string
	Geo        string
	GraphStore string
	Lineage    string
	Storage    string
}

type downstreamClient struct {
	urls   serviceURLs
	client *http.Client
}

func (c *downstreamClient) ingestImage(
	ctx context.Context,
	investigationID string,
	body []byte,
	contentType string,
) (Evidence, error) {
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		strings.TrimRight(c.urls.Ingest, "/")+"/v1/ingest/image",
		bytes.NewReader(body),
	)
	if err != nil {
		return Evidence{}, err
	}
	req.Header.Set("Content-Type", contentType)
	req.Header.Set("X-Investigation-Id", investigationID)
	var evidence Evidence
	err = c.doJSON(req, &evidence)
	return evidence, err
}

func (c *downstreamClient) invokeML(
	ctx context.Context,
	baseURL, endpoint string,
	payload map[string]any,
) ([]Observation, error) {
	req, err := jsonRequest(
		ctx,
		http.MethodPost,
		strings.TrimRight(baseURL, "/")+endpoint,
		payload,
	)
	if err != nil {
		return nil, err
	}
	var observations []Observation
	if err := c.doJSON(req, &observations); err != nil {
		return nil, err
	}
	return observations, nil
}

func (c *downstreamClient) createEntity(ctx context.Context, entity Entity) (Entity, error) {
	req, err := jsonRequest(
		ctx,
		http.MethodPost,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/entities",
		entity,
	)
	if err != nil {
		return Entity{}, err
	}
	var created Entity
	err = c.doJSON(req, &created)
	return created, err
}

func (c *downstreamClient) listEntities(
	ctx context.Context,
	investigationID, entityType string,
) (EntityList, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	if entityType != "" {
		query.Set("type", entityType)
	}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/entities?"+query.Encode(),
		nil,
	)
	if err != nil {
		return EntityList{}, err
	}
	var entities EntityList
	err = c.doJSON(req, &entities)
	return entities, err
}

func (c *downstreamClient) getEvidence(
	ctx context.Context,
	investigationID, evidenceID string,
) (Evidence, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.Storage, "/")+"/v1/evidence/"+
			url.PathEscape(evidenceID)+"?"+query.Encode(),
		nil,
	)
	if err != nil {
		return Evidence{}, err
	}
	req.Header.Set("X-Investigation-Id", investigationID)
	var evidence Evidence
	err = c.doJSON(req, &evidence)
	return evidence, err
}

func (c *downstreamClient) listEvidence(
	ctx context.Context,
	investigationID string,
) ([]Evidence, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.Storage, "/")+"/v1/evidence?"+query.Encode(),
		nil,
	)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Investigation-Id", investigationID)
	var response struct {
		Evidence []Evidence `json:"evidence"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return nil, err
	}
	return response.Evidence, nil
}

func (c *downstreamClient) listRuns(
	ctx context.Context,
	investigationID string,
) (RunsResponse, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.Lineage, "/")+"/v1/runs?"+query.Encode(),
		nil,
	)
	if err != nil {
		return RunsResponse{}, err
	}
	var runs RunsResponse
	err = c.doJSON(req, &runs)
	return runs, err
}

func (c *downstreamClient) health(ctx context.Context, baseURL string) error {
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(baseURL, "/")+"/healthz",
		nil,
	)
	if err != nil {
		return err
	}
	var status map[string]any
	return c.doJSON(req, &status)
}

func (c *downstreamClient) doJSON(req *http.Request, target any) error {
	resp, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		detail, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("%s returned %s: %s", req.URL.Host, resp.Status, strings.TrimSpace(string(detail)))
	}
	if target == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(target)
}

func jsonRequest(ctx context.Context, method, target string, body any) (*http.Request, error) {
	data, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	return req, nil
}
