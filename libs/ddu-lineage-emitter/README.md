# ddu-lineage-emitter

Go library for emitting OpenLineage RunEvents from any `ddu-*` service.

## Usage

```go
import "github.com/ddu/ddu-lineage-emitter"

client, err := lineageemitter.New(lineageemitter.Producer{
    Service:        "ddu-vision",
    ServiceVersion: "0.1.0",
    Tool:           "grounded-sam-2",
    ToolVersion:    "0.4.0",
})
if err != nil {
    log.Fatal(err)
}

runID := lineageemitter.NewRunID()
client.MustEmit(ctx, lineageemitter.Event{
    EventType: "START",
    RunID:     runID,
    JobName:   "ddu-vision:grounded-sam-2",
    Inputs: []lineageemitter.Input{
        {Namespace: "ddu.dev", Name: evidenceID, Type: "DDU.EVIDENCE"},
    },
})
// ... do work ...
client.MustEmit(ctx, lineageemitter.Event{
    EventType: "COMPLETE",
    RunID:     runID,
    JobName:   "ddu-vision:grounded-sam-2",
    Outputs:   []lineageemitter.Output{...},
})
```

## Environment

- `OPENLINEAGE_URL` — backend URL (Marquez in dev: `http://localhost:5000`)
- `OPENLINEAGE_NAMESPACE` — job namespace, defaults to `ddu.dev`
- `OPENLINEAGE_TIMEOUT` — HTTP timeout, defaults to `5s`

## Semantics

- Non-blocking on caller logic: errors returned but never panic.
- One retry with 500ms backoff on transient failure.
- Failed sends logged via `MustEmit`; provenance is best-effort but resilient.
