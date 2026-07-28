package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	dduhttpclient "github.com/ddu/ddu-httpclient"
	"github.com/ddu/ddu-lineage-emitter"
)

// Service metadata. Override via -ldflags at build time.
var (
	serviceName    = "ddu-api"
	serviceVersion = "0.0.0-dev"
	tool           = ""
	toolVersion    = ""
	model          = ""
	modelVersion   = ""
	gitCommit      = "unknown"
	builtAt        = "unknown"
)

func versionInfo() lineageemitter.Producer {
	return lineageemitter.Producer{
		Service:        serviceName,
		ServiceVersion: serviceVersion,
		Tool:           tool,
		ToolVersion:    toolVersion,
		Model:          model,
		ModelVersion:   modelVersion,
		GitCommit:      gitCommit,
	}
}

func main() {
	port := flag.Int("port", lookupEnvInt("PORT", 8001), "HTTP listen port")
	flag.Parse()

	urls := serviceURLs{
		Ingest:     lookupEnv("DDU_INGEST_URL", "http://localhost:8002"),
		Vision:     lookupEnv("DDU_VISION_URL", "http://localhost:8101"),
		OCR:        lookupEnv("DDU_OCR_URL", "http://localhost:8103"),
		Geo:        lookupEnv("DDU_GEO_URL", "http://localhost:8105"),
		Face:       lookupEnv("DDU_FACE_URL", "http://localhost:8102"),
		Audio:      lookupEnv("DDU_AUDIO_URL", "http://localhost:8104"),
		Temporal:   lookupEnv("DDU_TEMPORAL_URL", "http://localhost:8108"),
		GraphStore: lookupEnv("DDU_GRAPH_STORE_URL", "http://localhost:8004"),
		Lineage:    lookupEnv("DDU_LINEAGE_URL", "http://localhost:8006"),
		Storage:    lookupEnv("DDU_STORAGE_URL", "http://localhost:8003"),
		Discovery:  lookupEnv("DDU_DISCOVERY_URL", "http://localhost:8009"),
		OSINT:      lookupEnv("DDU_OSINT_URL", "http://localhost:8110"),
		Collector:  lookupEnv("DDU_COLLECTOR_URL", "http://localhost:8008"),
		Webcapture: lookupEnv("DDU_WEBCAPTURE_URL", "http://localhost:8007"),
		Resolution: lookupEnv("DDU_RESOLUTION_URL", "http://localhost:8111"),
		Agent:      lookupEnv("DDU_AGENT_URL", "http://localhost:8109"),
		Ontology:   lookupEnv("DDU_ONTOLOGY_URL", "http://localhost:8107"),
		Vector:     lookupEnv("DDU_VECTOR_URL", "http://localhost:8005"),
		Intel:      lookupEnv("DDU_INTEL_URL", "http://localhost:8112"),
	}
	lineage, err := lineageemitter.New(versionInfo())
	if err != nil {
		log.Printf("lineage emitter not initialized: %v (events will be dropped)", err)
	}

	httpClient := dduhttpclient.NewClient(dduhttpclient.Config{
		MaxRetries: 3,
		RetryDelay: 100 * time.Millisecond,
		CircuitBreaker: dduhttpclient.CircuitBreakerConfig{
			Enabled:     true,
			MaxRequests: 5,
			Interval:    30 * time.Second,
			Timeout:     60 * time.Second,
		},
		RateLimiter: dduhttpclient.RateLimiterConfig{
			Enabled: true,
			RPS:     100,
			Burst:   10,
		},
		Timeout: 5 * time.Minute,
	})

	srv := &http.Server{
		Addr:              fmt.Sprintf(":%d", *port),
		Handler:           newHandler(urls, httpClient, lineage),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       10 * time.Minute,
		WriteTimeout:      10 * time.Minute,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		log.Printf("%s listening on :%d", serviceName, *port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Printf("%s shutting down...", serviceName)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("shutdown: %v", err)
	}
}

func healthzHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"state":   "HEALTHY",
		"service": serviceName,
	})
}

func versionzHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{
		"service":         serviceName,
		"service_version": serviceVersion,
		"tool":            "workflow-orchestrator",
		"tool_version":    "1.0.0",
		"model":           model,
		"model_version":   modelVersion,
		"git_commit":      gitCommit,
		"built_at":        builtAt,
	})
}

func rootHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"service": serviceName,
		"version": serviceVersion,
		"status":  "ready",
		"endpoints": []string{
			"GET /healthz",
			"GET /versionz",
			"POST /v1/investigations",
			"GET /v1/investigations/{id}",
			"POST /v1/investigations/{id}/images",
			"POST /v1/investigations/{id}/usernames",
			"POST /v1/investigations/{id}/urls",
			"POST /v1/investigations/{id}/resolve",
			"POST /v1/investigations/{id}/agent",
			"GET /v1/investigations/{id}/timeline",
			"GET /v1/investigations/{id}/entities",
			"GET /v1/investigations/{id}/observations",
			"GET /v1/investigations/{id}/lineage",
			"GET /v1/investigations/{id}/relationships",
			"GET /v1/plugins",
		},
	})
}

func lookupEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func lookupEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil {
			return n
		}
	}
	return def
}
