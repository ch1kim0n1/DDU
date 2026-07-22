package lineageemitter

import (
	"strings"
	"testing"
)

func TestBuildPayloadUsesOpenLineageProducerURI(t *testing.T) {
	client := &Client{
		namespace: "ddu.test",
		producer: Producer{
			Service:        "ddu-storage",
			ServiceVersion: "0.0.1",
		},
	}

	payload := client.buildPayload(Event{
		EventType: "START",
		RunID:     "run-1",
		JobName:   "ddu-storage:store-evidence",
	})

	producer, ok := payload["producer"].(string)
	if !ok {
		t.Fatalf("producer type = %T, want string", payload["producer"])
	}
	if !strings.HasPrefix(producer, "https://ddu.local/") {
		t.Fatalf("producer = %q, want DDU producer URI", producer)
	}
}
