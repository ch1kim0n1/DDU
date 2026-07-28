package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

type fakeGraphRepository struct {
	entities      map[string]Entity
	relationships []Relationship
}

func newFakeGraphRepository() *fakeGraphRepository {
	return &fakeGraphRepository{entities: map[string]Entity{}}
}

func (f *fakeGraphRepository) Ping(context.Context) error { return nil }

func (f *fakeGraphRepository) CreateEntity(_ context.Context, entity Entity) (Entity, error) {
	f.entities[entity.ID] = entity
	return entity, nil
}

func (f *fakeGraphRepository) GetEntity(_ context.Context, id string) (Entity, error) {
	return f.entities[id], nil
}

func (f *fakeGraphRepository) ListEntities(_ context.Context, investigationID, entityType string) ([]Entity, error) {
	var result []Entity
	for _, entity := range f.entities {
		if entity.InvestigationID == investigationID && (entityType == "" || entity.Type == entityType) {
			result = append(result, entity)
		}
	}
	return result, nil
}

func (f *fakeGraphRepository) CreateRelationship(_ context.Context, relationship Relationship) (Relationship, error) {
	f.relationships = append(f.relationships, relationship)
	return relationship, nil
}

func (f *fakeGraphRepository) UpdateRelationshipVerification(
	_ context.Context, relationshipID, state, verifiedBy string,
) (Relationship, error) {
	for i, relationship := range f.relationships {
		if relationship.ID == relationshipID {
			relationship.VerificationState = state
			if relationship.Provenance.Parameters == nil {
				relationship.Provenance.Parameters = map[string]string{}
			}
			if verifiedBy != "" {
				relationship.Provenance.Parameters["verified_by"] = verifiedBy
			}
			f.relationships[i] = relationship
			return relationship, nil
		}
	}
	return Relationship{}, errNotFound
}

func (f *fakeGraphRepository) ListRelationships(_ context.Context, investigationID string) ([]Relationship, error) {
	var result []Relationship
	for _, relationship := range f.relationships {
		if relationship.InvestigationID == investigationID {
			result = append(result, relationship)
		}
	}
	return result, nil
}

func (f *fakeGraphRepository) Query(_ context.Context, _ string, _ map[string]any) ([]map[string]any, error) {
	return []map[string]any{{"ok": true}}, nil
}

func (f *fakeGraphRepository) Close(context.Context) error { return nil }

func TestEntityRelationshipAndQueryHandlers(t *testing.T) {
	repository := newFakeGraphRepository()
	handler := newHandler(repository, nil)

	entityBody := []byte(`{
		"investigation_id":"case-001",
		"type":"ENTITY_TYPE_OBSERVATION",
		"attributes":{"label":"vehicle"},
		"evidence_ids":["sha256:abc"],
		"provenance":{"produced_by_service":"ddu-vision","model_version":"0.4.0"}
	}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/entities", bytes.NewReader(entityBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create entity status = %d, body = %s", rec.Code, rec.Body.String())
	}
	var created Entity
	if err := json.NewDecoder(rec.Body).Decode(&created); err != nil {
		t.Fatal(err)
	}
	if created.ID == "" || created.Type != "ENTITY_TYPE_OBSERVATION" {
		t.Fatalf("created entity = %+v", created)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/entities/"+created.ID, nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("get entity status = %d", rec.Code)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/entities?investigation_id=case-001&type=ENTITY_TYPE_OBSERVATION", nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	var listed EntityList
	if err := json.NewDecoder(rec.Body).Decode(&listed); err != nil {
		t.Fatal(err)
	}
	if len(listed.Entities) != 1 || listed.Entities[0].ID != created.ID {
		t.Fatalf("listed entities = %+v", listed)
	}

	relationshipBody := []byte(`{
		"investigation_id":"case-001",
		"source_entity_id":"` + created.ID + `",
		"target_entity_id":"` + created.ID + `",
		"relationship_type":"EXTRACTED_FROM",
		"verification_state":"VERIFICATION_STATE_PENDING",
		"confidence":{"value":1},
		"evidence_ids":["sha256:abc"],
		"provenance":{"produced_by_service":"ddu-api"}
	}`)
	req = httptest.NewRequest(http.MethodPost, "/v1/relationships", bytes.NewReader(relationshipBody))
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create relationship status = %d, body = %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/relationships?investigation_id=case-001", nil)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	var relationships RelationshipList
	if err := json.NewDecoder(rec.Body).Decode(&relationships); err != nil {
		t.Fatal(err)
	}
	if len(relationships.Relationships) != 1 {
		t.Fatalf("relationships = %+v", relationships)
	}

	req = httptest.NewRequest(http.MethodPost, "/v1/query", bytes.NewBufferString(`{"cypher":"RETURN 1 AS ok"}`))
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || !bytes.Contains(rec.Body.Bytes(), []byte(`"ok":true`)) {
		t.Fatalf("query status = %d, body = %s", rec.Code, rec.Body.String())
	}
}
