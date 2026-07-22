module github.com/ddu/ddu-vector

go 1.22

require (
	github.com/ddu/ddu-lineage-emitter v0.0.0
	github.com/google/uuid v1.6.0
	github.com/qdrant/go-client v1.10.0
	google.golang.org/grpc v1.62.1
)

require (
	github.com/golang/protobuf v1.5.4 // indirect
	golang.org/x/net v0.22.0 // indirect
	golang.org/x/sys v0.18.0 // indirect
	golang.org/x/text v0.14.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20240311173647-c811ad7063a7 // indirect
	google.golang.org/protobuf v1.33.0 // indirect
)

replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter
