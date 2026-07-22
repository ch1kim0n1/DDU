package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"strconv"
	"strings"
	"time"

	evidence "github.com/ddu/ddu-evidence"
	lineageemitter "github.com/ddu/ddu-lineage-emitter"
)

const maxEvidenceBytes = 256 << 20

type evidenceStore interface {
	Put(context.Context, string, io.Reader, string) (string, error)
	Head(context.Context, string, string) (evidence.Meta, error)
	URI(string, string) string
	PutMetadata(context.Context, string, string, []byte) error
	GetMetadata(context.Context, string, string) ([]byte, error)
	ListMetadata(context.Context, string) ([][]byte, error)
	PresignGet(context.Context, string, string, time.Duration) (string, error)
	Ping(context.Context) error
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	store   evidenceStore
	lineage lineageEmitter
	now     func() time.Time
}

func newHandler(store evidenceStore, lineage lineageEmitter) http.Handler {
	s := &server{store: store, lineage: lineage, now: time.Now}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/evidence", s.uploadEvidence)
	mux.HandleFunc("GET /v1/evidence/{id}", s.getEvidence)
	mux.HandleFunc("GET /v1/evidence", s.listEvidence)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.store.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state":   "UNHEALTHY",
			"service": serviceName,
			"dependencies": []map[string]any{{
				"name": "minio", "ok": false, "detail": err.Error(),
			}},
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state":   "HEALTHY",
		"service": serviceName,
		"dependencies": []map[string]any{{
			"name": "minio", "ok": true, "detail": "reachable",
		}},
	})
}

func (s *server) uploadEvidence(w http.ResponseWriter, r *http.Request) {
	investigationID := investigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	runID := lineageemitter.NewRunID()
	s.emit(r.Context(), lineageemitter.Event{
		EventType: "START",
		RunID:     runID,
		JobName:   serviceName + ":store-evidence",
		Facets:    investigationFacet(investigationID),
	})

	r.Body = http.MaxBytesReader(w, r.Body, maxEvidenceBytes+(1<<20))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadRequest, "invalid multipart upload")
		return
	}
	file, header, err := evidenceFile(r)
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadRequest, "content file is required")
		return
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, maxEvidenceBytes+1))
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadRequest, "unable to read content")
		return
	}
	if len(content) > maxEvidenceBytes {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusRequestEntityTooLarge, "content exceeds 256 MiB")
		return
	}

	mimeType := strings.TrimSpace(r.FormValue("mime_type"))
	if mimeType == "" {
		mimeType = header.Header.Get("Content-Type")
	}
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = evidence.GuessMimeType(header.Filename)
	}
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = http.DetectContentType(content)
	}
	metadata, err := metadataField(r.FormValue("metadata"))
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadRequest, "metadata must be a string map")
		return
	}

	id, err := s.store.Put(r.Context(), investigationID, bytes.NewReader(content), mimeType)
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadGateway, "evidence storage failed")
		return
	}
	meta, err := s.store.Head(r.Context(), investigationID, id)
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadGateway, "evidence metadata lookup failed")
		return
	}

	record := Evidence{
		ID:                id,
		InvestigationID:   investigationID,
		Type:              evidenceType(mimeType),
		MimeType:          mimeType,
		SizeBytes:         meta.Size,
		StorageURI:        s.store.URI(investigationID, id),
		OriginURI:         strings.TrimSpace(r.FormValue("origin_uri")),
		AcquiredAt:        s.now().UTC().Format(time.RFC3339Nano),
		OriginalTimestamp: strings.TrimSpace(r.FormValue("original_timestamp")),
		Metadata:          metadata,
		AcquiredBy:        defaultString(r.FormValue("acquired_by"), serviceName),
		AcquisitionMethod: defaultString(r.FormValue("acquisition_method"), "user-upload"),
		ParentEvidenceIDs: stringListField(r.FormValue("parent_evidence_ids")),
		IsOriginal:        boolField(r.FormValue("is_original"), true),
	}
	data, err := json.Marshal(record)
	if err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusInternalServerError, "evidence metadata encoding failed")
		return
	}
	if err := s.store.PutMetadata(r.Context(), investigationID, id, data); err != nil {
		s.fail(r.Context(), runID, "store-evidence", investigationID)
		writeError(w, http.StatusBadGateway, "evidence metadata storage failed")
		return
	}

	s.emit(r.Context(), lineageemitter.Event{
		EventType: "COMPLETE",
		RunID:     runID,
		JobName:   serviceName + ":store-evidence",
		Outputs: []lineageemitter.Output{{
			Namespace: investigationID,
			Name:      id,
			Type:      "DDU.EVIDENCE",
		}},
		Facets: investigationFacet(investigationID),
	})
	writeJSON(w, http.StatusCreated, record)
}

func (s *server) getEvidence(w http.ResponseWriter, r *http.Request) {
	investigationID := investigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	id := r.PathValue("id")
	runID := lineageemitter.NewRunID()
	s.emit(r.Context(), lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":get-evidence",
		Inputs: []lineageemitter.Input{{Namespace: investigationID, Name: id, Type: "DDU.EVIDENCE"}},
		Facets: investigationFacet(investigationID),
	})
	data, err := s.store.GetMetadata(r.Context(), investigationID, id)
	if err != nil {
		s.fail(r.Context(), runID, "get-evidence", investigationID)
		writeError(w, http.StatusNotFound, "evidence not found")
		return
	}
	var record Evidence
	if err := json.Unmarshal(data, &record); err != nil {
		s.fail(r.Context(), runID, "get-evidence", investigationID)
		writeError(w, http.StatusInternalServerError, "stored evidence metadata is invalid")
		return
	}
	url, err := s.store.PresignGet(r.Context(), investigationID, id, 15*time.Minute)
	if err != nil {
		s.fail(r.Context(), runID, "get-evidence", investigationID)
		writeError(w, http.StatusBadGateway, "download URL generation failed")
		return
	}
	s.emit(r.Context(), lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":get-evidence",
		Inputs: []lineageemitter.Input{{Namespace: investigationID, Name: id, Type: "DDU.EVIDENCE"}},
		Facets: investigationFacet(investigationID),
	})
	writeJSON(w, http.StatusOK, EvidenceResponse{Evidence: record, DownloadURL: url})
}

func (s *server) listEvidence(w http.ResponseWriter, r *http.Request) {
	investigationID := investigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "investigation_id is required")
		return
	}
	runID := lineageemitter.NewRunID()
	s.emit(r.Context(), lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":list-evidence",
		Facets: investigationFacet(investigationID),
	})
	data, err := s.store.ListMetadata(r.Context(), investigationID)
	if err != nil {
		s.fail(r.Context(), runID, "list-evidence", investigationID)
		writeError(w, http.StatusBadGateway, "evidence listing failed")
		return
	}
	records := make([]Evidence, 0, len(data))
	for _, item := range data {
		var record Evidence
		if err := json.Unmarshal(item, &record); err != nil {
			s.fail(r.Context(), runID, "list-evidence", investigationID)
			writeError(w, http.StatusInternalServerError, "stored evidence metadata is invalid")
			return
		}
		records = append(records, record)
	}
	s.emit(r.Context(), lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":list-evidence",
		Facets: investigationFacet(investigationID),
	})
	writeJSON(w, http.StatusOK, EvidenceList{Evidence: records})
}

func evidenceFile(r *http.Request) (multipart.File, *multipart.FileHeader, error) {
	file, header, err := r.FormFile("content")
	if err == nil {
		return file, header, nil
	}
	return r.FormFile("file")
}

func metadataField(raw string) (map[string]string, error) {
	if strings.TrimSpace(raw) == "" {
		return map[string]string{}, nil
	}
	var metadata map[string]string
	if err := json.Unmarshal([]byte(raw), &metadata); err != nil {
		return nil, err
	}
	if metadata == nil {
		metadata = map[string]string{}
	}
	return metadata, nil
}

func stringListField(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return []string{}
	}
	var values []string
	if json.Unmarshal([]byte(raw), &values) == nil {
		return values
	}
	parts := strings.Split(raw, ",")
	values = values[:0]
	for _, part := range parts {
		if value := strings.TrimSpace(part); value != "" {
			values = append(values, value)
		}
	}
	return values
}

func evidenceType(mimeType string) string {
	switch {
	case strings.HasPrefix(mimeType, "image/"):
		return "EVIDENCE_TYPE_IMAGE"
	case strings.HasPrefix(mimeType, "video/"):
		return "EVIDENCE_TYPE_VIDEO"
	case strings.HasPrefix(mimeType, "audio/"):
		return "EVIDENCE_TYPE_AUDIO"
	case mimeType == "application/warc" || mimeType == "application/warc+gzip":
		return "EVIDENCE_TYPE_WEB_SNAPSHOT"
	default:
		return "EVIDENCE_TYPE_DOCUMENT"
	}
}

func investigationID(r *http.Request) string {
	if value := strings.TrimSpace(r.Header.Get("X-Investigation-Id")); value != "" {
		return value
	}
	return strings.TrimSpace(r.URL.Query().Get("investigation_id"))
}

func defaultString(value, fallback string) string {
	if value = strings.TrimSpace(value); value != "" {
		return value
	}
	return fallback
}

func boolField(value string, fallback bool) bool {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func investigationFacet(investigationID string) map[string]string {
	value, _ := json.Marshal(map[string]string{"investigation_id": investigationID})
	return map[string]string{"dduInvestigation": string(value)}
}

func (s *server) fail(ctx context.Context, runID, job, investigationID string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "FAIL",
		RunID:     runID,
		JobName:   serviceName + ":" + job,
		Facets:    investigationFacet(investigationID),
	})
}

func (s *server) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil && !errors.Is(err, context.Canceled) {
		return
	}
}
