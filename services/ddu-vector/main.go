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

	"github.com/ddu/ddu-lineage-emitter"
)

// Service metadata. Override via -ldflags at build time.
var (
	serviceName    = "ddu-vector"
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
	port := flag.Int("port", lookupEnvInt("PORT", 8005), "HTTP listen port")
	flag.Parse()

	qdrantURL := os.Getenv("QDRANT_URL")
	if qdrantURL == "" {
		qdrantURL = "http://localhost:6333"
	}
	connectContext, cancelConnect := context.WithTimeout(context.Background(), 5*time.Second)
	repository, err := newQdrantRepository(connectContext, qdrantURL)
	cancelConnect()
	if err != nil {
		log.Fatalf("connect to Qdrant: %v", err)
	}
	defer repository.Close()

	lineage, err := lineageemitter.New(versionInfo())
	if err != nil {
		log.Printf("lineage emitter not initialized: %v (events will be dropped)", err)
	}

	srv := &http.Server{
		Addr:              fmt.Sprintf(":%d", *port),
		Handler:           newHandler(repository, lineage),
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
		"tool":            "qdrant",
		"tool_version":    "1.10.0",
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
			"POST /v1/collections",
			"POST /v1/points/upsert",
			"POST /v1/search",
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
