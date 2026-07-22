package main

import (
	"context"
	"fmt"
	"math"
	"net"
	"net/url"
	"strconv"

	"github.com/google/uuid"
	pb "github.com/qdrant/go-client/qdrant"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const originalPointIDKey = "_ddu_point_id"

type qdrantRepository struct {
	connection  *grpc.ClientConn
	health      pb.QdrantClient
	collections pb.CollectionsClient
	points      pb.PointsClient
}

func newQdrantRepository(ctx context.Context, rawURL string) (*qdrantRepository, error) {
	address, err := qdrantGRPCAddress(rawURL)
	if err != nil {
		return nil, err
	}
	connection, err := grpc.DialContext(ctx, address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	repository := &qdrantRepository{
		connection:  connection,
		health:      pb.NewQdrantClient(connection),
		collections: pb.NewCollectionsClient(connection),
		points:      pb.NewPointsClient(connection),
	}
	if err := repository.Ping(ctx); err != nil {
		connection.Close()
		return nil, err
	}
	return repository, nil
}

func (r *qdrantRepository) Ping(ctx context.Context) error {
	_, err := r.health.HealthCheck(ctx, &pb.HealthCheckRequest{})
	return err
}

func (r *qdrantRepository) Close() error {
	return r.connection.Close()
}

func (r *qdrantRepository) CreateCollection(ctx context.Context, name string, size uint64, distance string) error {
	_, err := r.collections.Create(ctx, &pb.CreateCollection{
		CollectionName: name,
		VectorsConfig: &pb.VectorsConfig{Config: &pb.VectorsConfig_Params{
			Params: &pb.VectorParams{Size: size, Distance: qdrantDistance(distance)},
		}},
	})
	return err
}

func (r *qdrantRepository) Upsert(ctx context.Context, collection string, points []Point) error {
	qdrantPoints := make([]*pb.PointStruct, 0, len(points))
	for _, point := range points {
		payload := make(map[string]*pb.Value, len(point.Payload)+1)
		for key, value := range point.Payload {
			payload[key] = qdrantValue(value)
		}
		payload[originalPointIDKey] = qdrantValue(point.ID)
		qdrantPoints = append(qdrantPoints, &pb.PointStruct{
			Id: &pb.PointId{PointIdOptions: &pb.PointId_Uuid{
				Uuid: uuid.NewSHA1(uuid.NameSpaceURL, []byte("ddu:"+point.ID)).String(),
			}},
			Vectors: &pb.Vectors{VectorsOptions: &pb.Vectors_Vector{
				Vector: &pb.Vector{Data: point.Vector},
			}},
			Payload: payload,
		})
	}
	wait := true
	_, err := r.points.Upsert(ctx, &pb.UpsertPoints{
		CollectionName: collection,
		Wait:           &wait,
		Points:         qdrantPoints,
	})
	return err
}

func (r *qdrantRepository) Search(ctx context.Context, request SearchRequest) ([]Match, error) {
	filter, err := qdrantFilter(request.Filter)
	if err != nil {
		return nil, err
	}
	response, err := r.points.Search(ctx, &pb.SearchPoints{
		CollectionName: request.Collection,
		Vector:         request.Vector,
		Limit:          request.Limit,
		Filter:         filter,
		WithPayload: &pb.WithPayloadSelector{SelectorOptions: &pb.WithPayloadSelector_Enable{
			Enable: true,
		}},
		WithVectors: &pb.WithVectorsSelector{SelectorOptions: &pb.WithVectorsSelector_Enable{
			Enable: request.WithVectors,
		}},
	})
	if err != nil {
		return nil, err
	}
	matches := make([]Match, 0, len(response.GetResult()))
	for _, result := range response.GetResult() {
		payload := make(map[string]any, len(result.GetPayload()))
		for key, value := range result.GetPayload() {
			payload[key] = nativeValue(value)
		}
		id, _ := payload[originalPointIDKey].(string)
		if id == "" {
			id = pointIDString(result.GetId())
		}
		delete(payload, originalPointIDKey)
		match := Match{ID: id, Score: result.GetScore(), Payload: payload}
		if request.WithVectors && result.GetVectors() != nil && result.GetVectors().GetVector() != nil {
			match.Vector = result.GetVectors().GetVector().GetData()
		}
		matches = append(matches, match)
	}
	return matches, nil
}

func qdrantGRPCAddress(rawURL string) (string, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "", err
	}
	host := parsed.Hostname()
	if host == "" {
		host = parsed.Path
	}
	if host == "" {
		return "", fmt.Errorf("QDRANT_URL must include a host")
	}
	port := parsed.Port()
	if port == "" || port == "6333" {
		port = "6334"
	}
	return net.JoinHostPort(host, port), nil
}

func qdrantDistance(distance string) pb.Distance {
	switch distance {
	case "DOT":
		return pb.Distance_Dot
	case "EUCLID":
		return pb.Distance_Euclid
	case "MANHATTAN":
		return pb.Distance_Manhattan
	default:
		return pb.Distance_Cosine
	}
}

func qdrantFilter(values map[string]any) (*pb.Filter, error) {
	if len(values) == 0 {
		return nil, nil
	}
	conditions := make([]*pb.Condition, 0, len(values))
	for key, value := range values {
		match := &pb.Match{}
		switch typed := value.(type) {
		case string:
			match.MatchValue = &pb.Match_Keyword{Keyword: typed}
		case bool:
			match.MatchValue = &pb.Match_Boolean{Boolean: typed}
		case float64:
			if math.Trunc(typed) != typed {
				return nil, fmt.Errorf("filter %q must be a string, boolean, or integer", key)
			}
			match.MatchValue = &pb.Match_Integer{Integer: int64(typed)}
		default:
			return nil, fmt.Errorf("unsupported filter value for %q", key)
		}
		conditions = append(conditions, &pb.Condition{ConditionOneOf: &pb.Condition_Field{
			Field: &pb.FieldCondition{Key: key, Match: match},
		}})
	}
	return &pb.Filter{Must: conditions}, nil
}

func qdrantValue(value any) *pb.Value {
	switch typed := value.(type) {
	case nil:
		return &pb.Value{Kind: &pb.Value_NullValue{NullValue: pb.NullValue_NULL_VALUE}}
	case bool:
		return &pb.Value{Kind: &pb.Value_BoolValue{BoolValue: typed}}
	case string:
		return &pb.Value{Kind: &pb.Value_StringValue{StringValue: typed}}
	case float64:
		if math.Trunc(typed) == typed {
			return &pb.Value{Kind: &pb.Value_IntegerValue{IntegerValue: int64(typed)}}
		}
		return &pb.Value{Kind: &pb.Value_DoubleValue{DoubleValue: typed}}
	case float32:
		return &pb.Value{Kind: &pb.Value_DoubleValue{DoubleValue: float64(typed)}}
	case int:
		return &pb.Value{Kind: &pb.Value_IntegerValue{IntegerValue: int64(typed)}}
	case int64:
		return &pb.Value{Kind: &pb.Value_IntegerValue{IntegerValue: typed}}
	case []any:
		values := make([]*pb.Value, 0, len(typed))
		for _, item := range typed {
			values = append(values, qdrantValue(item))
		}
		return &pb.Value{Kind: &pb.Value_ListValue{ListValue: &pb.ListValue{Values: values}}}
	case map[string]any:
		fields := make(map[string]*pb.Value, len(typed))
		for key, item := range typed {
			fields[key] = qdrantValue(item)
		}
		return &pb.Value{Kind: &pb.Value_StructValue{StructValue: &pb.Struct{Fields: fields}}}
	default:
		return &pb.Value{Kind: &pb.Value_StringValue{StringValue: fmt.Sprint(typed)}}
	}
}

func nativeValue(value *pb.Value) any {
	if value == nil {
		return nil
	}
	switch typed := value.Kind.(type) {
	case *pb.Value_NullValue:
		return nil
	case *pb.Value_BoolValue:
		return typed.BoolValue
	case *pb.Value_StringValue:
		return typed.StringValue
	case *pb.Value_IntegerValue:
		return typed.IntegerValue
	case *pb.Value_DoubleValue:
		return typed.DoubleValue
	case *pb.Value_ListValue:
		values := make([]any, 0, len(typed.ListValue.GetValues()))
		for _, item := range typed.ListValue.GetValues() {
			values = append(values, nativeValue(item))
		}
		return values
	case *pb.Value_StructValue:
		fields := make(map[string]any, len(typed.StructValue.GetFields()))
		for key, item := range typed.StructValue.GetFields() {
			fields[key] = nativeValue(item)
		}
		return fields
	default:
		return nil
	}
}

func pointIDString(id *pb.PointId) string {
	if id == nil {
		return ""
	}
	if value := id.GetUuid(); value != "" {
		return value
	}
	return strconv.FormatUint(id.GetNum(), 10)
}
