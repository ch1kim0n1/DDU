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
	"strconv"
	"syscall"
	"time"

	evidence "github.com/ddu/ddu-evidence"
	"github.com/ddu/ddu-lineage-emitter"
)

// Service metadata. Override via -ldflags at build time.
var (
	serviceName    = "ddu-storage"
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
	port := flag.Int("port", lookupEnvInt("PORT", 8003), "HTTP listen port")
	flag.Parse()

	store, err := evidence.New(context.Background(), evidence.Options{
		Endpoint:        lookupEnv("MINIO_ENDPOINT", "http://localhost:9000"),
		AccessKeyID:     lookupEnv("MINIO_ACCESS_KEY", "dduadmin"),
		SecretAccessKey: lookupEnv("MINIO_SECRET_KEY", "ddudevpass"),
		Bucket:          lookupEnv("MINIO_BUCKET", evidence.DefaultEvidenceBucket),
		UsePathStyle:    lookupEnvBool("MINIO_USE_PATH_STYLE", true),
	})
	if err != nil {
		log.Fatalf("initialize evidence store: %v", err)
	}
	var emitter lineageEmitter
	lineage, err := lineageemitter.New(versionInfo())
	if err != nil {
		log.Printf("lineage emitter not initialized: %v (events will be dropped)", err)
	} else {
		emitter = lineage
	}

	srv := &http.Server{
		Addr:              fmt.Sprintf(":%d", *port),
		Handler:           newHandler(store, emitter),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       60 * time.Second,
		WriteTimeout:      60 * time.Second,
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
		"tool":            tool,
		"tool_version":    toolVersion,
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
			"POST /v1/evidence",
			"GET /v1/evidence/{id}",
			"GET /v1/evidence",
		},
	})
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

func lookupEnv(key, def string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return def
}

func lookupEnvBool(key string, def bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return def
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return def
	}
	return parsed
}
