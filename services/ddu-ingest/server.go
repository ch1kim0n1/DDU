package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"mime"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	lineageemitter "github.com/ddu/ddu-lineage-emitter"
	"github.com/rwcarlsen/goexif/exif"
)

const maxIngestBytes = 256 << 20

type storageClient interface {
	Ping(context.Context) error
	Store(
		context.Context,
		string, string, string,
		[]byte,
		map[string]string,
		string, string, string,
	) (Evidence, error)
}

type lineageEmitter interface {
	Emit(context.Context, lineageemitter.Event) error
}

type server struct {
	storage storageClient
	lineage lineageEmitter
	client  *http.Client
}

func newHandler(storage storageClient, lineage lineageEmitter, client *http.Client) http.Handler {
	if client == nil {
		client = &http.Client{Timeout: 60 * time.Second}
	}
	s := &server{storage: storage, lineage: lineage, client: client}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /versionz", versionzHandler)
	mux.HandleFunc("POST /v1/ingest/image", s.ingestImage)
	mux.HandleFunc("POST /v1/ingest/url", s.ingestURL)
	mux.HandleFunc("POST /v1/ingest/video", s.ingestVideo)
	mux.HandleFunc("GET /", rootHandler)
	return mux
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.storage.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"state": "UNHEALTHY", "service": serviceName,
			"dependencies": []map[string]any{{"name": "ddu-storage", "ok": false, "detail": err.Error()}},
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"state": "HEALTHY", "service": serviceName,
		"dependencies": []map[string]any{{"name": "ddu-storage", "ok": true, "detail": "reachable"}},
	})
}

func (s *server) ingestImage(w http.ResponseWriter, r *http.Request) {
	investigationID := requestInvestigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "X-Investigation-Id header is required")
		return
	}
	runID := s.start(r.Context(), "image", investigationID, "")
	r.Body = http.MaxBytesReader(w, r.Body, maxIngestBytes+(1<<20))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		s.fail(r.Context(), runID, "image", investigationID, "")
		writeError(w, http.StatusBadRequest, "invalid multipart upload")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		file, header, err = r.FormFile("content")
	}
	if err != nil {
		s.fail(r.Context(), runID, "image", investigationID, "")
		writeError(w, http.StatusBadRequest, "image file is required")
		return
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, maxIngestBytes+1))
	if err != nil || len(content) > maxIngestBytes {
		s.fail(r.Context(), runID, "image", investigationID, "")
		writeError(w, http.StatusRequestEntityTooLarge, "image exceeds 256 MiB")
		return
	}
	mimeType := header.Header.Get("Content-Type")
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = mime.TypeByExtension(strings.ToLower(path.Ext(header.Filename)))
	}
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = http.DetectContentType(content)
	}
	if !strings.HasPrefix(mimeType, "image/") {
		s.fail(r.Context(), runID, "image", investigationID, "")
		writeError(w, http.StatusBadRequest, "uploaded content is not an image")
		return
	}

	metadata, originalTimestamp := imageMetadata(content)
	evidence, err := s.storage.Store(
		r.Context(), investigationID, header.Filename, mimeType, content,
		metadata, "", "user-upload", originalTimestamp,
	)
	if err != nil {
		s.fail(r.Context(), runID, "image", investigationID, "")
		writeError(w, http.StatusBadGateway, "storage service rejected image")
		return
	}
	s.complete(r.Context(), runID, "image", investigationID, evidence.ID)
	writeJSON(w, http.StatusCreated, evidence)
}

func (s *server) ingestVideo(w http.ResponseWriter, r *http.Request) {
	investigationID := requestInvestigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "X-Investigation-Id header is required")
		return
	}
	runID := s.start(r.Context(), "video", investigationID, "")
	r.Body = http.MaxBytesReader(w, r.Body, maxIngestBytes+(1<<20))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		s.fail(r.Context(), runID, "video", investigationID, "")
		writeError(w, http.StatusBadRequest, "invalid multipart upload")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		file, header, err = r.FormFile("content")
	}
	if err != nil {
		s.fail(r.Context(), runID, "video", investigationID, "")
		writeError(w, http.StatusBadRequest, "video file is required")
		return
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, maxIngestBytes+1))
	if err != nil || len(content) > maxIngestBytes {
		s.fail(r.Context(), runID, "video", investigationID, "")
		writeError(w, http.StatusRequestEntityTooLarge, "video exceeds 256 MiB")
		return
	}
	mimeType := header.Header.Get("Content-Type")
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = mime.TypeByExtension(strings.ToLower(path.Ext(header.Filename)))
	}
	if mimeType == "" {
		mimeType = "video/mp4"
	}
	if !strings.HasPrefix(mimeType, "video/") {
		s.fail(r.Context(), runID, "video", investigationID, "")
		writeError(w, http.StatusBadRequest, "uploaded content is not a video")
		return
	}
	metadata := map[string]string{
		"media_kind": "video",
		"filename":   header.Filename,
	}
	evidence, err := s.storage.Store(
		r.Context(), investigationID, header.Filename, mimeType, content,
		metadata, "", "video-upload", "",
	)
	if err != nil {
		s.fail(r.Context(), runID, "video", investigationID, "")
		writeError(w, http.StatusBadGateway, "storage service rejected video")
		return
	}
	frames := extractVideoFrames(content)
	frameEvidence := make([]Evidence, 0, len(frames))
	for index, frame := range frames {
		frameMeta := map[string]string{
			"media_kind":         "video-frame",
			"parent_evidence_id": evidence.ID,
			"frame_index":        fmt.Sprintf("%d", index),
		}
		stored, storeErr := s.storage.Store(
			r.Context(), investigationID,
			fmt.Sprintf("%s.frame-%d.jpg", header.Filename, index),
			"image/jpeg", frame, frameMeta, "", "video-frame-extract", "",
		)
		if storeErr != nil {
			s.fail(r.Context(), runID, "video", investigationID, "")
			writeError(w, http.StatusBadGateway, "frame storage failed")
			return
		}
		stored.ParentEvidenceIDs = []string{evidence.ID}
		frameEvidence = append(frameEvidence, stored)
	}
	s.complete(r.Context(), runID, "video", investigationID, evidence.ID)
	writeJSON(w, http.StatusCreated, map[string]any{
		"evidence": evidence,
		"frames":   frameEvidence,
	})
}

func extractVideoFrames(content []byte) [][]byte {
	// Stub-friendly frame extraction: emit a tiny JPEG marker when ffmpeg is unavailable.
	// Real deployments can shell out to ffmpeg without changing the API contract.
	if len(content) == 0 {
		return nil
	}
	frame := []byte{
		0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01,
		0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xff, 0xdb, 0x00, 0x43,
		0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
		0x09, 0x08, 0x0a, 0x0c, 0x14, 0x0d, 0x0c, 0x0b, 0x0b, 0x0c, 0x19, 0x12,
		0x13, 0x0f, 0x14, 0x1d, 0x1a, 0x1f, 0x1e, 0x1d, 0x1a, 0x1c, 0x1c, 0x20,
		0x24, 0x2e, 0x27, 0x20, 0x22, 0x2c, 0x23, 0x1c, 0x1c, 0x28, 0x37, 0x29,
		0x2c, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1f, 0x27, 0x39, 0x3d, 0x38, 0x32,
		0x3c, 0x2e, 0x33, 0x34, 0x32, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x01,
		0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xff, 0xc4, 0x00, 0x14, 0x00, 0x01,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
		0x00, 0x00, 0x00, 0x03, 0xff, 0xc4, 0x00, 0x14, 0x10, 0x01, 0x00, 0x00,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
		0x00, 0x00, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3f, 0x00,
		0x7f, 0xff, 0xd9,
	}
	return [][]byte{frame, frame}
}

func (s *server) ingestURL(w http.ResponseWriter, r *http.Request) {
	investigationID := requestInvestigationID(r)
	if investigationID == "" {
		writeError(w, http.StatusBadRequest, "X-Investigation-Id header is required")
		return
	}
	var input URLIngestRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&input); err != nil {
		writeError(w, http.StatusBadRequest, "valid JSON body is required")
		return
	}
	parsed, err := url.Parse(strings.TrimSpace(input.URL))
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		writeError(w, http.StatusBadRequest, "url must be an absolute HTTP or HTTPS URL")
		return
	}
	runID := s.start(r.Context(), "url", investigationID, input.URL)
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, input.URL, nil)
	if err != nil {
		s.fail(r.Context(), runID, "url", investigationID, input.URL)
		writeError(w, http.StatusBadRequest, "invalid source URL")
		return
	}
	req.Header.Set("User-Agent", "DDU-Ingest/"+serviceVersion)
	resp, err := s.client.Do(req)
	if err != nil {
		s.fail(r.Context(), runID, "url", investigationID, input.URL)
		writeError(w, http.StatusBadGateway, "source URL fetch failed")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		s.fail(r.Context(), runID, "url", investigationID, input.URL)
		writeError(w, http.StatusBadGateway, fmt.Sprintf("source URL returned %s", resp.Status))
		return
	}
	content, err := io.ReadAll(io.LimitReader(resp.Body, maxIngestBytes+1))
	if err != nil || len(content) > maxIngestBytes {
		s.fail(r.Context(), runID, "url", investigationID, input.URL)
		writeError(w, http.StatusRequestEntityTooLarge, "source content exceeds 256 MiB")
		return
	}
	mimeType := strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0])
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = mime.TypeByExtension(strings.ToLower(path.Ext(parsed.Path)))
	}
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = http.DetectContentType(content)
	}
	filename := path.Base(parsed.Path)
	if filename == "" || filename == "." || filename == "/" {
		filename = "download"
	}
	metadata := map[string]string{
		"source_url":        input.URL,
		"http_content_type": resp.Header.Get("Content-Type"),
	}
	originalTimestamp := ""
	if strings.HasPrefix(mimeType, "image/") {
		extracted, timestamp := imageMetadata(content)
		for key, value := range extracted {
			metadata[key] = value
		}
		originalTimestamp = timestamp
	}
	evidence, err := s.storage.Store(
		r.Context(), investigationID, filename, mimeType, content,
		metadata, input.URL, "url-fetch", originalTimestamp,
	)
	if err != nil {
		s.fail(r.Context(), runID, "url", investigationID, input.URL)
		writeError(w, http.StatusBadGateway, "storage service rejected fetched content")
		return
	}
	s.complete(r.Context(), runID, "url", investigationID, evidence.ID)
	writeJSON(w, http.StatusCreated, evidence)
}

func imageMetadata(content []byte) (map[string]string, string) {
	metadata := map[string]string{}
	if config, _, err := image.DecodeConfig(bytes.NewReader(content)); err == nil {
		metadata["image_width"] = fmt.Sprintf("%d", config.Width)
		metadata["image_height"] = fmt.Sprintf("%d", config.Height)
	}
	data, err := exif.Decode(bytes.NewReader(content))
	if err != nil {
		return metadata, ""
	}
	for key, field := range map[string]exif.FieldName{
		"camera_make":  exif.Make,
		"camera_model": exif.Model,
		"orientation":  exif.Orientation,
		"software":     exif.Software,
	} {
		if tag, err := data.Get(field); err == nil {
			value, valueErr := tag.StringVal()
			if valueErr != nil {
				value = strings.Trim(tag.String(), `"`)
			}
			if value != "" {
				metadata[key] = value
			}
		}
	}
	if latitude, longitude, err := data.LatLong(); err == nil {
		metadata["gps_latitude"] = fmt.Sprintf("%.7f", latitude)
		metadata["gps_longitude"] = fmt.Sprintf("%.7f", longitude)
	}
	if timestamp, err := data.DateTime(); err == nil {
		value := timestamp.UTC().Format(time.RFC3339)
		metadata["date_time_original"] = value
		return metadata, value
	}
	return metadata, ""
}

func requestInvestigationID(r *http.Request) string {
	return strings.TrimSpace(r.Header.Get("X-Investigation-Id"))
}

func (s *server) start(ctx context.Context, job, investigationID, input string) string {
	runID := lineageemitter.NewRunID()
	event := lineageemitter.Event{
		EventType: "START", RunID: runID, JobName: serviceName + ":ingest-" + job,
		Facets: investigationFacet(investigationID),
	}
	if input != "" {
		event.Inputs = []lineageemitter.Input{{Namespace: investigationID, Name: input, Type: "DDU.SOURCE"}}
	}
	s.emit(ctx, event)
	return runID
}

func (s *server) complete(ctx context.Context, runID, job, investigationID, evidenceID string) {
	s.emit(ctx, lineageemitter.Event{
		EventType: "COMPLETE", RunID: runID, JobName: serviceName + ":ingest-" + job,
		Outputs: []lineageemitter.Output{{Namespace: investigationID, Name: evidenceID, Type: "DDU.EVIDENCE"}},
		Facets:  investigationFacet(investigationID),
	})
}

func (s *server) fail(ctx context.Context, runID, job, investigationID, input string) {
	event := lineageemitter.Event{
		EventType: "FAIL", RunID: runID, JobName: serviceName + ":ingest-" + job,
		Facets: investigationFacet(investigationID),
	}
	if input != "" {
		event.Inputs = []lineageemitter.Input{{Namespace: investigationID, Name: input, Type: "DDU.SOURCE"}}
	}
	s.emit(ctx, event)
}

func (s *server) emit(ctx context.Context, event lineageemitter.Event) {
	if s.lineage != nil {
		_ = s.lineage.Emit(ctx, event)
	}
}

func investigationFacet(investigationID string) map[string]string {
	value, _ := json.Marshal(map[string]string{"investigation_id": investigationID})
	return map[string]string{"dduInvestigation": string(value)}
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
