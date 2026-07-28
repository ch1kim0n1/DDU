package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

type browsertrixAdapter struct {
	baseURL string
	apiKey  string
	client  *http.Client
}

func newBrowsertrixAdapter(client *http.Client) *browsertrixAdapter {
	baseURL := strings.TrimSpace(os.Getenv("BROWSERTRIX_URL"))
	if baseURL == "" {
		baseURL = "http://localhost:8000"
	}
	return &browsertrixAdapter{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  os.Getenv("BROWSERTRIX_API_KEY"),
		client:  client,
	}
}

type browsertrixCrawlRequest struct {
	URL         string `json:"url"`
	WaitSeconds int    `json:"waitSeconds,omitempty"`
}

type browsertrixCrawlResponse struct {
	WARCURL string `json:"warcUrl"`
	ID      string `json:"id"`
}

func (a *browsertrixAdapter) Capture(ctx context.Context, url string, waitSeconds int) ([]byte, string, error) {
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		return stubWARC(url), "capture.warc.gz", nil
	}
	payload := browsertrixCrawlRequest{URL: url, WaitSeconds: waitSeconds}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.baseURL+"/api/crawl", bytes.NewReader(body))
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if a.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+a.apiKey)
	}
	resp, err := a.client.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("browsertrix crawl request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		detail, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, "", fmt.Errorf("browsertrix returned %s: %s", resp.Status, strings.TrimSpace(string(detail)))
	}
	var result browsertrixCrawlResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, "", fmt.Errorf("browsertrix response parse failed: %w", err)
	}
	if result.WARCURL == "" {
		return nil, "", fmt.Errorf("browsertrix returned empty warc url")
	}
	warcContent, err := a.downloadWARC(ctx, result.WARCURL)
	if err != nil {
		return nil, "", err
	}
	return warcContent, "capture.warc.gz", nil
}

func (a *browsertrixAdapter) downloadWARC(ctx context.Context, warcURL string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, warcURL, nil)
	if err != nil {
		return nil, err
	}
	if a.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+a.apiKey)
	}
	resp, err := a.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("warc download failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= http.StatusBadRequest {
		return nil, fmt.Errorf("warc download returned %s", resp.Status)
	}
	content, err := io.ReadAll(io.LimitReader(resp.Body, 512<<20))
	if err != nil {
		return nil, err
	}
	return content, nil
}

func stubWARC(url string) []byte {
	header := fmt.Sprintf("WARC/1.0\r\nWARC-Type: response\r\nWARC-Date: %s\r\nWARC-Target-URI: %s\r\nContent-Type: application/http; msgtype=response\r\n\r\n",
		time.Now().UTC().Format(time.RFC3339), url)
	return []byte(header + "HTTP/1.1 200 OK\r\n\r\nstub-warc-content\r\n\r\n")
}
