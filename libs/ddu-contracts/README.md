// DDU Contracts — protobuf definitions
//
// These schemas are the stable boundary between DDU core and every ddu-* service.
// Both Go and Python services generate stubs from the same .proto files.
//
// Generate Go stubs:
//   buf generate
//   # or directly:
//   protoc -I proto --go_out=go --go_opt=module=github.com/ddu/ddu-contracts/go \
//     --go-grpc_out=go --go-grpc_opt=module=github.com/ddu/ddu-contracts/go \
//     proto/ddu/*.proto
//
// Generate Python stubs:
//   python -m grpc_tools.protoc -I proto \
//     --python_out=python/ddu_contractsv1 --pyi_out=python/ddu_contractsv1 \
//     --grpc_python_out=python/ddu_contractsv1 \
//     proto/ddu/*.proto
//
// Contracts in this directory:
//   service.proto              — service version + health probes
//   provenance.proto           — provenance block, epistemic classes, confidence
//   evidence.proto             — immutable evidence objects (MinIO-backed)
//   observation.proto          — directly-detected observations
//   candidate_relationship.proto — machine-proposed associations (never verified)
//   entity.proto               — canonical entities + verified relationships
//   lineage.proto              — OpenLineage event wrapper
//
// Design rules:
//   1. Every derived artifact carries a Provenance block.
//   2. Every candidate output carries a Confidence value.
//   3. Epistemic classes are never collapsed. Observation != Inference != Fact.
//   4. CandidateRelationships are never auto-promoted to Relationships.
//   5. Evidence is immutable and content-addressed (sha256).
//   6. Every service invocation emits a LineageEvent.
