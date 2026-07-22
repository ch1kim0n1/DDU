module github.com/ddu/ddu-api

go 1.22

require (
	github.com/ddu/ddu-lineage-emitter v0.0.0
	github.com/go-chi/chi/v5 v5.2.5
	github.com/google/uuid v1.6.0
)

replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter
