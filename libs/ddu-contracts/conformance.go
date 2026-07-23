package dducontracts

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"testing"
	"time"
)

// ServiceContract defines the expected interface for all DDU services
type ServiceContract struct {
	BaseURL    string
	HTTPClient *http.Client
}

// NewServiceContract creates a new contract tester for a service
func NewServiceContract(baseURL string) *ServiceContract {
	return &ServiceContract{
		BaseURL: baseURL,
		HTTPClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// TestHealthz verifies GET /healthz returns proper response
func (c *ServiceContract) TestHealthz(t *testing.T) {
	resp, err := c.HTTPClient.Get(c.BaseURL + "/healthz")
	if err != nil {
		t.Fatalf("healthz request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("healthz returned status %d, expected %d", resp.StatusCode, http.StatusOK)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("failed to read healthz response: %v", err)
	}

	var result struct {
		State   string `json:"state"`
		Service string `json:"service"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatalf("healthz response is not valid JSON: %v", err)
	}

	if result.State != "HEALTHY" && result.State != "DEGRADED" {
		t.Fatalf("healthz state is %s, expected HEALTHY or DEGRADED", result.State)
	}

	if result.Service == "" {
		t.Error("healthz response missing service field")
	}
}

// TestVersionz verifies GET /versionz returns proper response
func (c *ServiceContract) TestVersionz(t *testing.T) {
	resp, err := c.HTTPClient.Get(c.BaseURL + "/versionz")
	if err != nil {
		t.Fatalf("versionz request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("versionz returned status %d, expected %d", resp.StatusCode, http.StatusOK)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("failed to read versionz response: %v", err)
	}

	var result map[string]string
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatalf("versionz response is not valid JSON: %v", err)
	}

	requiredFields := []string{"service", "service_version"}
	for _, field := range requiredFields {
		if _, ok := result[field]; !ok {
			t.Errorf("versionz response missing required field: %s", field)
		}
	}

	// Optional fields that should be present if set
	optionalFields := []string{"tool", "tool_version", "model", "model_version", "git_commit", "built_at"}
	for _, field := range optionalFields {
		if val, ok := result[field]; ok && val != "" {
			t.Logf("versionz includes optional field %s: %s", field, val)
		}
	}
}

// TestRootEndpoint verifies GET / returns service info
func (c *ServiceContract) TestRootEndpoint(t *testing.T) {
	resp, err := c.HTTPClient.Get(c.BaseURL + "/")
	if err != nil {
		t.Fatalf("root request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("root returned status %d, expected %d", resp.StatusCode, http.StatusOK)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("failed to read root response: %v", err)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		t.Fatalf("root response is not valid JSON: %v", err)
	}

	if _, ok := result["service"]; !ok {
		t.Error("root response missing service field")
	}
	if _, ok := result["endpoints"]; !ok {
		t.Error("root response missing endpoints field")
	}
}

// TestContentType verifies responses are JSON
func (c *ServiceContract) TestContentType(t *testing.T, endpoint string) {
	resp, err := c.HTTPClient.Get(c.BaseURL + endpoint)
	if err != nil {
		t.Fatalf("%s request failed: %v", endpoint, err)
	}
	defer resp.Body.Close()

	contentType := resp.Header.Get("Content-Type")
	if contentType != "application/json" {
		t.Errorf("%s returned Content-Type %s, expected application/json", endpoint, contentType)
	}
}

// RunAllContractTests runs all standard contract tests for a service
func (c *ServiceContract) RunAllContractTests(t *testing.T) {
	t.Run("Healthz", c.TestHealthz)
	t.Run("Versionz", c.TestVersionz)
	t.Run("RootEndpoint", c.TestRootEndpoint)
	t.Run("HealthzContentType", func(t *testing.T) {
		c.TestContentType(t, "/healthz")
	})
	t.Run("VersionzContentType", func(t *testing.T) {
		c.TestContentType(t, "/versionz")
	})
}

// WaitForService waits for a service to become healthy
func (c *ServiceContract) WaitForService(maxWait time.Duration) error {
	deadline := time.Now().Add(maxWait)
	for time.Now().Before(deadline) {
		resp, err := c.HTTPClient.Get(c.BaseURL + "/healthz")
		if err == nil {
			defer resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("service did not become healthy within %v", maxWait)
}