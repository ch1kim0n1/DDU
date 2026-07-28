module github.com/ddu/ddu-graph-store

go 1.22

require (
	github.com/ddu/ddu-lineage-emitter v0.0.0
	github.com/google/uuid v1.6.0
	github.com/neo4j/neo4j-go-driver/v5 v5.20.0
)

replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter
