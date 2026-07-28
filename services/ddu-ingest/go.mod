module github.com/ddu/ddu-ingest

go 1.22

require (
	github.com/ddu/ddu-lineage-emitter v0.0.0
	github.com/rwcarlsen/goexif v0.0.0-20190401172101-9e8deecbddbd
)

require github.com/google/uuid v1.6.0 // indirect

replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter
