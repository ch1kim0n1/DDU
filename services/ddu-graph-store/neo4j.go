package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
)

var (
	errNotFound = errors.New("not found")
	tokenRE     = regexp.MustCompile(`^[A-Z][A-Z0-9_]*$`)
)

type neo4jRepository struct {
	driver neo4j.DriverWithContext
}

func newNeo4jRepository(ctx context.Context, uri, user, password string) (*neo4jRepository, error) {
	driver, err := neo4j.NewDriverWithContext(uri, neo4j.BasicAuth(user, password, ""))
	if err != nil {
		return nil, err
	}
	repository := &neo4jRepository{driver: driver}
	if err := repository.Ping(ctx); err != nil {
		_ = driver.Close(ctx)
		return nil, err
	}
	session := driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer session.Close(ctx)
	if _, err := session.Run(ctx,
		"CREATE CONSTRAINT ddu_entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
		nil,
	); err != nil {
		_ = driver.Close(ctx)
		return nil, err
	}
	return repository, nil
}

func (r *neo4jRepository) Ping(ctx context.Context) error {
	return r.driver.VerifyConnectivity(ctx)
}

func (r *neo4jRepository) Close(ctx context.Context) error {
	return r.driver.Close(ctx)
}

func (r *neo4jRepository) CreateEntity(ctx context.Context, entity Entity) (Entity, error) {
	label, err := entityLabel(entity.Type)
	if err != nil {
		return Entity{}, err
	}
	record, err := json.Marshal(entity)
	if err != nil {
		return Entity{}, err
	}
	attributes := make(map[string]any, len(entity.Attributes))
	for key, value := range entity.Attributes {
		if safePropertyKey(key) {
			attributes[key] = value
		}
	}
	evidenceIDs, _ := json.Marshal(entity.EvidenceIDs)
	provenance, _ := json.Marshal(entity.Provenance)
	properties := map[string]any{
		"id":               entity.ID,
		"investigation_id": entity.InvestigationID,
		"entity_type":      entity.Type,
		"evidence_ids":     string(evidenceIDs),
		"provenance":       string(provenance),
		"created_at":       entity.CreatedAt,
		"updated_at":       entity.UpdatedAt,
		"record_json":      string(record),
	}
	query := "CREATE (n:Entity:" + label + ") SET n += $attributes SET n += $properties RETURN n.record_json AS record"
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer session.Close(ctx)
	result, err := session.Run(ctx, query, map[string]any{"attributes": attributes, "properties": properties})
	if err != nil {
		return Entity{}, err
	}
	if _, err := result.Single(ctx); err != nil {
		return Entity{}, err
	}
	return entity, nil
}

func (r *neo4jRepository) GetEntity(ctx context.Context, id string) (Entity, error) {
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer session.Close(ctx)
	result, err := session.Run(ctx,
		"MATCH (n:Entity {id: $id}) RETURN n.record_json AS record",
		map[string]any{"id": id},
	)
	if err != nil {
		return Entity{}, err
	}
	if !result.Next(ctx) {
		if err := result.Err(); err != nil {
			return Entity{}, err
		}
		return Entity{}, errNotFound
	}
	return decodeEntityRecord(result.Record())
}

func (r *neo4jRepository) ListEntities(ctx context.Context, investigationID, entityType string) ([]Entity, error) {
	query := "MATCH (n:Entity {investigation_id: $investigation_id})"
	parameters := map[string]any{"investigation_id": investigationID}
	if entityType != "" {
		query += " WHERE n.entity_type = $entity_type"
		parameters["entity_type"] = entityType
	}
	query += " RETURN n.record_json AS record ORDER BY n.created_at, n.id"
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer session.Close(ctx)
	result, err := session.Run(ctx, query, parameters)
	if err != nil {
		return nil, err
	}
	var entities []Entity
	for result.Next(ctx) {
		entity, err := decodeEntityRecord(result.Record())
		if err != nil {
			return nil, err
		}
		entities = append(entities, entity)
	}
	if err := result.Err(); err != nil {
		return nil, err
	}
	return entities, nil
}

func (r *neo4jRepository) CreateRelationship(ctx context.Context, relationship Relationship) (Relationship, error) {
	relationshipType := strings.ToUpper(strings.TrimSpace(relationship.RelationshipType))
	if !tokenRE.MatchString(relationshipType) {
		return Relationship{}, errors.New("invalid relationship_type")
	}
	record, err := json.Marshal(relationship)
	if err != nil {
		return Relationship{}, err
	}
	evidenceIDs, _ := json.Marshal(relationship.EvidenceIDs)
	confidence, _ := json.Marshal(relationship.Confidence)
	provenance, _ := json.Marshal(relationship.Provenance)
	properties := map[string]any{
		"id":                        relationship.ID,
		"investigation_id":          relationship.InvestigationID,
		"relationship_type":         relationship.RelationshipType,
		"verification_state":        relationship.VerificationState,
		"confidence":                float64(relationship.Confidence.Value),
		"confidence_json":           string(confidence),
		"evidence_ids":              string(evidenceIDs),
		"candidate_relationship_id": relationship.CandidateRelationshipID,
		"provenance":                string(provenance),
		"created_at":                relationship.CreatedAt,
		"updated_at":                relationship.UpdatedAt,
		"record_json":               string(record),
	}
	query := "MATCH (source:Entity {id: $source_id}), (target:Entity {id: $target_id}) " +
		"WHERE source.investigation_id = $investigation_id AND target.investigation_id = $investigation_id " +
		"CREATE (source)-[r:" + relationshipType + "]->(target) SET r = $properties RETURN r.record_json AS record"
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer session.Close(ctx)
	result, err := session.Run(ctx, query, map[string]any{
		"source_id": relationship.SourceEntityID, "target_id": relationship.TargetEntityID,
		"investigation_id": relationship.InvestigationID, "properties": properties,
	})
	if err != nil {
		return Relationship{}, err
	}
	if !result.Next(ctx) {
		if err := result.Err(); err != nil {
			return Relationship{}, err
		}
		return Relationship{}, errNotFound
	}
	return relationship, nil
}

func (r *neo4jRepository) UpdateRelationshipVerification(
	ctx context.Context,
	relationshipID, state, verifiedBy string,
) (Relationship, error) {
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer session.Close(ctx)
	result, err := session.Run(ctx,
		"MATCH ()-[rel]->() WHERE rel.id = $id RETURN rel.record_json AS record",
		map[string]any{"id": relationshipID},
	)
	if err != nil {
		return Relationship{}, err
	}
	if !result.Next(ctx) {
		if err := result.Err(); err != nil {
			return Relationship{}, err
		}
		return Relationship{}, errNotFound
	}
	raw, _ := result.Record().Get("record")
	rawString, _ := raw.(string)
	var relationship Relationship
	if err := json.Unmarshal([]byte(rawString), &relationship); err != nil {
		return Relationship{}, err
	}
	relationship.VerificationState = state
	relationship.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if relationship.Provenance.Parameters == nil {
		relationship.Provenance.Parameters = map[string]string{}
	}
	if verifiedBy != "" {
		relationship.Provenance.Parameters["verified_by"] = verifiedBy
	}
	record, err := json.Marshal(relationship)
	if err != nil {
		return Relationship{}, err
	}
	_, err = session.Run(ctx,
		"MATCH ()-[rel]->() WHERE rel.id = $id SET rel.verification_state = $state, "+
			"rel.updated_at = $updated_at, rel.record_json = $record RETURN rel.id",
		map[string]any{
			"id": relationshipID, "state": state,
			"updated_at": relationship.UpdatedAt, "record": string(record),
		},
	)
	if err != nil {
		return Relationship{}, err
	}
	return relationship, nil
}

func (r *neo4jRepository) ListRelationships(ctx context.Context, investigationID string) ([]Relationship, error) {
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeRead})
	defer session.Close(ctx)
	result, err := session.Run(ctx,
		"MATCH (:Entity)-[r]->(:Entity) WHERE r.investigation_id = $investigation_id "+
			"RETURN r.record_json AS record ORDER BY r.created_at, r.id",
		map[string]any{"investigation_id": investigationID},
	)
	if err != nil {
		return nil, err
	}
	var relationships []Relationship
	for result.Next(ctx) {
		value, ok := result.Record().Get("record")
		if !ok {
			return nil, errors.New("relationship record missing")
		}
		raw, ok := value.(string)
		if !ok {
			return nil, errors.New("relationship record invalid")
		}
		var relationship Relationship
		if err := json.Unmarshal([]byte(raw), &relationship); err != nil {
			return nil, err
		}
		relationships = append(relationships, relationship)
	}
	if err := result.Err(); err != nil {
		return nil, err
	}
	return relationships, nil
}

func (r *neo4jRepository) Query(ctx context.Context, cypher string, parameters map[string]any) ([]map[string]any, error) {
	session := r.driver.NewSession(ctx, neo4j.SessionConfig{AccessMode: neo4j.AccessModeWrite})
	defer session.Close(ctx)
	result, err := session.Run(ctx, cypher, parameters)
	if err != nil {
		return nil, err
	}
	var records []map[string]any
	for result.Next(ctx) {
		item := make(map[string]any, len(result.Record().Keys))
		for index, key := range result.Record().Keys {
			item[key] = normalizeNeo4jValue(result.Record().Values[index])
		}
		records = append(records, item)
	}
	if err := result.Err(); err != nil {
		return nil, err
	}
	return records, nil
}

func decodeEntityRecord(record *neo4j.Record) (Entity, error) {
	value, ok := record.Get("record")
	if !ok {
		return Entity{}, errors.New("entity record missing")
	}
	raw, ok := value.(string)
	if !ok {
		return Entity{}, errors.New("entity record invalid")
	}
	var entity Entity
	if err := json.Unmarshal([]byte(raw), &entity); err != nil {
		return Entity{}, err
	}
	return entity, nil
}

func entityLabel(entityType string) (string, error) {
	label := strings.TrimPrefix(strings.ToUpper(strings.TrimSpace(entityType)), "ENTITY_TYPE_")
	if !tokenRE.MatchString(label) {
		return "", errors.New("invalid entity type")
	}
	return label, nil
}

func safePropertyKey(key string) bool {
	return tokenRE.MatchString(strings.ToUpper(key))
}

func normalizeNeo4jValue(value any) any {
	switch typed := value.(type) {
	case neo4j.Node:
		return map[string]any{
			"element_id": typed.ElementId,
			"labels":     typed.Labels,
			"properties": typed.Props,
		}
	case neo4j.Relationship:
		return map[string]any{
			"element_id":       typed.ElementId,
			"start_element_id": typed.StartElementId,
			"end_element_id":   typed.EndElementId,
			"type":             typed.Type,
			"properties":       typed.Props,
		}
	case []any:
		result := make([]any, len(typed))
		for index, item := range typed {
			result[index] = normalizeNeo4jValue(item)
		}
		return result
	case map[string]any:
		result := make(map[string]any, len(typed))
		for key, item := range typed {
			result[key] = normalizeNeo4jValue(item)
		}
		return result
	default:
		return value
	}
}

func neo4jURL(value string) string {
	if strings.TrimSpace(value) == "" {
		return "bolt://localhost:7687"
	}
	return value
}

func neo4jCredentials(user, password string) (string, string) {
	if user == "" {
		user = "neo4j"
	}
	if password == "" {
		password = "ddudevpass"
	}
	return user, password
}

func invalidTokenError(kind, value string) error {
	return fmt.Errorf("invalid %s %q", kind, value)
}
