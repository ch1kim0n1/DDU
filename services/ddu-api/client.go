package main

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

	dduhttpclient "github.com/ddu/ddu-httpclient"
)

type serviceURLs struct {
	Ingest      string
	Vision      string
	OCR         string
	Geo         string
	Face        string
	Audio       string
	Temporal    string
	GraphStore  string
	Lineage     string
	Storage     string
	Discovery   string
	OSINT       string
	Collector   string
	Webcapture  string
	Resolution  string
	Agent       string
	Ontology    string
	Vector      string
	Intel       string
}

type downstreamClient struct {
	urls   serviceURLs
	client *dduhttpclient.Client
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

func (c *downstreamClient) listRelationships(
	ctx context.Context,
	investigationID string,
) (RelationshipList, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/relationships?"+query.Encode(),
		nil,
	)
	if err != nil {
		return RelationshipList{}, err
	}
	var relationships RelationshipList
	err = c.doJSON(req, &relationships)
	return relationships, err
}

func (c *downstreamClient) createRelationship(
	ctx context.Context,
	relationship Relationship,
) (Relationship, error) {
	req, err := jsonRequest(
		ctx,
		http.MethodPost,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/relationships",
		relationship,
	)
	if err != nil {
		return Relationship{}, err
	}
	var created Relationship
	err = c.doJSON(req, &created)
	return created, err
}

func (c *downstreamClient) updateRelationshipVerification(
	ctx context.Context,
	relationshipID, state, actor string,
) (Relationship, error) {
	req, err := jsonRequest(
		ctx,
		http.MethodPatch,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/relationships/"+url.PathEscape(relationshipID)+"/verification",
		map[string]string{"verification_state": state, "verified_by": actor},
	)
	if err != nil {
		return Relationship{}, err
	}
	var updated Relationship
	err = c.doJSON(req, &updated)
	return updated, err
}

func (c *downstreamClient) discoverUsername(
	ctx context.Context,
	investigationID, username string,
	sites []string,
) ([]Observation, error) {
	if sites == nil {
		sites = []string{}
	}
	payload := map[string]any{
		"investigation_id": investigationID,
		"username":         username,
		"sites":            sites,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Discovery, "/")+"/v1/discover", payload)
	if err != nil {
		return nil, err
	}
	var response struct {
		Observations []Observation `json:"observations"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return nil, err
	}
	return response.Observations, nil
}

func (c *downstreamClient) enrichOSINT(
	ctx context.Context,
	investigationID, target string,
	modules []string,
) ([]Observation, error) {
	if modules == nil {
		modules = []string{}
	}
	payload := map[string]any{
		"investigation_id": investigationID,
		"target":           target,
		"modules":          modules,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.OSINT, "/")+"/v1/enrich", payload)
	if err != nil {
		return nil, err
	}
	var observations []Observation
	err = c.doJSON(req, &observations)
	return observations, err
}

func (c *downstreamClient) collectURL(
	ctx context.Context,
	investigationID, sourceURL string,
) ([]Evidence, error) {
	payload := map[string]any{
		"investigation_id": investigationID,
		"url":              sourceURL,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Collector, "/")+"/v1/collect", payload)
	if err != nil {
		return nil, err
	}
	var response struct {
		Evidence []Evidence `json:"evidence"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return nil, err
	}
	return response.Evidence, nil
}

func (c *downstreamClient) captureURL(
	ctx context.Context,
	investigationID, sourceURL string,
) (Evidence, error) {
	payload := map[string]any{
		"investigation_id": investigationID,
		"url":              sourceURL,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Webcapture, "/")+"/v1/capture", payload)
	if err != nil {
		return Evidence{}, err
	}
	var response struct {
		Evidence Evidence `json:"evidence"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return Evidence{}, err
	}
	return response.Evidence, nil
}

func (c *downstreamClient) resolveEntities(
	ctx context.Context,
	investigationID string,
	entityIDs []string,
	threshold float64,
) ([]CandidateRelationship, error) {
	if entityIDs == nil {
		entityIDs = []string{}
	}
	payload := map[string]any{
		"investigation_id": investigationID,
		"entity_ids":       entityIDs,
		"threshold":        threshold,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Resolution, "/")+"/v1/resolve", payload)
	if err != nil {
		return nil, err
	}
	var candidates []CandidateRelationship
	err = c.doJSON(req, &candidates)
	return candidates, err
}

func (c *downstreamClient) contradict(
	ctx context.Context,
	investigationID string,
) ([]map[string]any, error) {
	payload := map[string]any{"investigation_id": investigationID}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Resolution, "/")+"/v1/contradict", payload)
	if err != nil {
		return nil, err
	}
	var contradictions []map[string]any
	err = c.doJSON(req, &contradictions)
	return contradictions, err
}

func (c *downstreamClient) runAgentWorkflow(
	ctx context.Context,
	endpoint string,
	payload map[string]any,
) (map[string]any, error) {
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Agent, "/")+endpoint, payload)
	if err != nil {
		return nil, err
	}
	var result map[string]any
	err = c.doJSON(req, &result)
	return result, err
}

func (c *downstreamClient) createSnapshot(
	ctx context.Context,
	investigationID, label string,
) (map[string]any, error) {
	payload := map[string]any{"investigation_id": investigationID, "label": label}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.GraphStore, "/")+"/v1/snapshots", payload)
	if err != nil {
		return nil, err
	}
	var snapshot map[string]any
	err = c.doJSON(req, &snapshot)
	return snapshot, err
}

func (c *downstreamClient) listSnapshots(
	ctx context.Context,
	investigationID string,
) ([]map[string]any, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.GraphStore, "/")+"/v1/snapshots?"+query.Encode(),
		nil,
	)
	if err != nil {
		return nil, err
	}
	var response struct {
		Snapshots []map[string]any `json:"snapshots"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return nil, err
	}
	return response.Snapshots, nil
}

func (c *downstreamClient) temporalTimeline(
	ctx context.Context,
	investigationID string,
) ([]map[string]any, error) {
	query := url.Values{"investigation_id": []string{investigationID}}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		strings.TrimRight(c.urls.Temporal, "/")+"/v1/timeline?"+query.Encode(),
		nil,
	)
	if err != nil {
		return nil, err
	}
	var response struct {
		Events []map[string]any `json:"events"`
	}
	if err := c.doJSON(req, &response); err != nil {
		return nil, err
	}
	return response.Events, nil
}

func (c *downstreamClient) upsertVectors(
	ctx context.Context,
	investigationID, collection string,
	points []map[string]any,
) error {
	payload := map[string]any{
		"collection":       collection,
		"points":           points,
		"investigation_id": investigationID,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Vector, "/")+"/v1/points/upsert", payload)
	if err != nil {
		return err
	}
	return c.doJSON(req, nil)
}

func (c *downstreamClient) intelPOST(
	ctx context.Context,
	endpoint string,
	payload map[string]any,
) (map[string]any, error) {
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Intel, "/")+endpoint, payload)
	if err != nil {
		return nil, err
	}
	var body map[string]any
	err = c.doJSON(req, &body)
	return body, err
}

func (c *downstreamClient) intelGET(
	ctx context.Context,
	endpoint, investigationID string,
) (map[string]any, error) {
	target := strings.TrimRight(c.urls.Intel, "/") + endpoint
	if investigationID != "" {
		target += "?investigation_id=" + url.QueryEscape(investigationID)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	var body map[string]any
	err = c.doJSON(req, &body)
	return body, err
}

func (c *downstreamClient) listOntologyTypes(
	ctx context.Context,
	investigationID string,
) (map[string]any, error) {
	query := url.Values{}
	if investigationID != "" {
		query.Set("investigation_id", investigationID)
	}
	target := strings.TrimRight(c.urls.Ontology, "/") + "/v1/entity-types"
	if encoded := query.Encode(); encoded != "" {
		target += "?" + encoded
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	var body map[string]any
	err = c.doJSON(req, &body)
	return body, err
}

func (c *downstreamClient) createOntologyType(
	ctx context.Context,
	payload map[string]any,
) (map[string]any, error) {
	req, err := jsonRequest(
		ctx,
		http.MethodPost,
		strings.TrimRight(c.urls.Ontology, "/")+"/v1/entity-types",
		payload,
	)
	if err != nil {
		return nil, err
	}
	var body map[string]any
	err = c.doJSON(req, &body)
	return body, err
}

func (c *downstreamClient) ensureCollection(
	ctx context.Context,
	investigationID, name string,
	vectorSize uint64,
) error {
	payload := map[string]any{
		"name":             name,
		"vector_size":      vectorSize,
		"distance":         "COSINE",
		"investigation_id": investigationID,
	}
	req, err := jsonRequest(ctx, http.MethodPost, strings.TrimRight(c.urls.Vector, "/")+"/v1/collections", payload)
	if err != nil {
		return err
	}
	// Collection may already exist; treat non-2xx as non-fatal at call site.
	return c.doJSON(req, nil)
}

func (c *downstreamClient) appendAudit(entry map[string]any) {
	// Always emit structured audit to process log.
	raw, _ := json.Marshal(entry)
	fmt.Printf("ddu-audit %s\n", string(raw))
	if strings.ToLower(strings.TrimSpace(os.Getenv("DDU_AUDIT_ENABLED"))) != "true" {
		return
	}
	if strings.TrimSpace(c.urls.Storage) == "" {
		return
	}
	payload := map[string]any{
		"bucket": "ddu-audit",
		"key": fmt.Sprintf(
			"audit/%v/%v.json",
			entry["investigation_id"],
			entry["request_id"],
		),
		"content_type": "application/json",
		"body":         entry,
	}
	req, err := jsonRequest(context.Background(), http.MethodPost, strings.TrimRight(c.urls.Storage, "/")+"/v1/objects", payload)
	if err != nil {
		return
	}
	resp, err := c.client.Do(context.Background(), req)
	if err != nil {
		return
	}
	resp.Body.Close()
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
	resp, err := c.client.Do(req.Context(), req)
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
