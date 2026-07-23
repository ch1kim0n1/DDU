package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	dduhttpclient "github.com/ddu/ddu-httpclient"
)

// investigationStore persists investigations beyond process lifetime via graph-store
// (ENTITY_TYPE_INVESTIGATION nodes in Neo4j).
type investigationStore struct {
	mu      sync.RWMutex
	cache   map[string]Investigation
	client  *dduhttpclient.Client
	baseURL string
}

func newInvestigationStore(baseURL string, client *dduhttpclient.Client) *investigationStore {
	if client == nil {
		client = dduhttpclient.NewClient(dduhttpclient.Config{Timeout: 30 * time.Second})
	}
	return &investigationStore{
		cache:   map[string]Investigation{},
		client:  client,
		baseURL: strings.TrimRight(baseURL, "/"),
	}
}

func (s *investigationStore) Put(ctx context.Context, inv Investigation) error {
	s.mu.Lock()
	s.cache[inv.ID] = inv
	s.mu.Unlock()
	if err := s.persist(ctx, inv); err != nil {
		// Keep serving from cache; caller treats persistence as best-effort.
		return err
	}
	return nil
}

func (s *investigationStore) Get(ctx context.Context, id string) (Investigation, bool) {
	s.mu.RLock()
	inv, ok := s.cache[id]
	s.mu.RUnlock()
	if ok {
		return inv, true
	}
	loaded, err := s.loadOne(ctx, id)
	if err != nil {
		return Investigation{}, false
	}
	s.mu.Lock()
	s.cache[id] = loaded
	s.mu.Unlock()
	return loaded, true
}

func (s *investigationStore) List(ctx context.Context) []Investigation {
	_ = s.refresh(ctx)
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Investigation, 0, len(s.cache))
	for _, inv := range s.cache {
		out = append(out, inv)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	return out
}

func (s *investigationStore) persist(ctx context.Context, inv Investigation) error {
	if s.baseURL == "" {
		return nil
	}
	members, _ := json.Marshal(inv.Members)
	payload := map[string]any{
		"id":               inv.ID,
		"investigation_id": inv.ID,
		"type":             "ENTITY_TYPE_INVESTIGATION",
		"attributes": map[string]string{
			"name":       inv.Name,
			"created_at": inv.CreatedAt,
			"members":    string(members),
			"ddu_kind":   "investigation",
		},
		"evidence_ids": []string{},
		"provenance": map[string]any{
			"produced_by_service": "ddu-api",
			"job_name":            "ddu-api:persist-investigation",
		},
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.baseURL+"/v1/entities", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.client.Do(ctx, req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("persist investigation: %s", string(raw))
	}
	return nil
}

func (s *investigationStore) refresh(ctx context.Context) error {
	if s.baseURL == "" {
		return nil
	}
	req, err := http.NewRequestWithContext(
		ctx, http.MethodGet,
		s.baseURL+"/v1/entities?type="+url.QueryEscape("ENTITY_TYPE_INVESTIGATION"),
		nil,
	)
	if err != nil {
		return err
	}
	resp, err := s.client.Do(ctx, req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("list investigations status %d", resp.StatusCode)
	}
	var body struct {
		Entities []Entity `json:"entities"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, entity := range body.Entities {
		inv := entityToInvestigation(entity)
		if inv.ID == "" {
			continue
		}
		s.cache[inv.ID] = inv
	}
	return nil
}

func (s *investigationStore) loadOne(ctx context.Context, id string) (Investigation, error) {
	if err := s.refresh(ctx); err != nil {
		return Investigation{}, err
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	inv, ok := s.cache[id]
	if !ok {
		return Investigation{}, fmt.Errorf("not found")
	}
	return inv, nil
}

func entityToInvestigation(entity Entity) Investigation {
	attrs := entity.Attributes
	if attrs == nil {
		attrs = map[string]string{}
	}
	if attrs["ddu_kind"] != "investigation" && entity.Type != "ENTITY_TYPE_INVESTIGATION" {
		return Investigation{}
	}
	id := entity.ID
	if entity.InvestigationID != "" {
		id = entity.InvestigationID
	}
	inv := Investigation{
		ID:        id,
		Name:      attrs["name"],
		CreatedAt: attrs["created_at"],
	}
	if inv.Name == "" {
		inv.Name = id
	}
	if raw := attrs["members"]; raw != "" {
		var members []InvestigationMember
		if json.Unmarshal([]byte(raw), &members) == nil {
			inv.Members = members
		}
	}
	return inv
}
