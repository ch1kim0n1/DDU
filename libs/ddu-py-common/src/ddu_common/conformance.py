"""Service contract conformance tests for DDU services."""

import json
import time
from typing import Optional
import httpx


class ServiceContract:
    """Test suite for DDU service contract conformance."""
    
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()
    
    def test_healthz(self) -> dict:
        """Test GET /healthz endpoint."""
        response = self.client.get(f"{self.base_url}/healthz")
        response.raise_for_status()
        
        data = response.json()
        assert "state" in data, "healthz response missing 'state' field"
        assert data["state"] in ["HEALTHY", "DEGRADED"], f"Invalid state: {data['state']}"
        assert "service" in data, "healthz response missing 'service' field"
        
        return data
    
    def test_versionz(self) -> dict:
        """Test GET /versionz endpoint."""
        response = self.client.get(f"{self.base_url}/versionz")
        response.raise_for_status()
        
        data = response.json()
        required_fields = ["service", "service_version"]
        for field in required_fields:
            assert field in data, f"versionz response missing required field: {field}"
        
        # Log optional fields if present
        optional_fields = ["tool", "tool_version", "model", "model_version", "git_commit", "built_at"]
        for field in optional_fields:
            if field in data and data[field]:
                print(f"versionz includes optional field {field}: {data[field]}")
        
        return data
    
    def test_root_endpoint(self) -> dict:
        """Test GET / endpoint."""
        response = self.client.get(f"{self.base_url}/")
        response.raise_for_status()
        
        data = response.json()
        assert "service" in data, "root response missing 'service' field"
        assert "endpoints" in data, "root response missing 'endpoints' field"
        
        return data
    
    def test_content_type(self, endpoint: str) -> str:
        """Test that endpoint returns JSON content type."""
        response = self.client.get(f"{self.base_url}{endpoint}")
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type, f"{endpoint} returned content-type: {content_type}"
        return content_type
    
    def run_all_tests(self) -> dict:
        """Run all contract tests and return results."""
        results = {
            "healthz": None,
            "versionz": None,
            "root_endpoint": None,
            "healthz_content_type": None,
            "versionz_content_type": None,
        }
        
        try:
            results["healthz"] = self.test_healthz()
        except Exception as e:
            results["healthz"] = {"error": str(e)}
        
        try:
            results["versionz"] = self.test_versionz()
        except Exception as e:
            results["versionz"] = {"error": str(e)}
        
        try:
            results["root_endpoint"] = self.test_root_endpoint()
        except Exception as e:
            results["root_endpoint"] = {"error": str(e)}
        
        try:
            results["healthz_content_type"] = self.test_content_type("/healthz")
        except Exception as e:
            results["healthz_content_type"] = {"error": str(e)}
        
        try:
            results["versionz_content_type"] = self.test_content_type("/versionz")
        except Exception as e:
            results["versionz_content_type"] = {"error": str(e)}
        
        return results
    
    def wait_for_service(self, max_wait: float = 30.0, interval: float = 0.5) -> bool:
        """Wait for service to become healthy."""
        start = time.time()
        while time.time() - start < max_wait:
            try:
                response = self.client.get(f"{self.base_url}/healthz", timeout=2.0)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False


def run_contract_test(base_url: str, service_name: str) -> bool:
    """Run contract tests for a service and print results."""
    print(f"Testing {service_name} at {base_url}")
    
    contract = ServiceContract(base_url)
    
    # Wait for service to be ready
    if not contract.wait_for_service(max_wait=5.0):
        print(f"  SKIP: {service_name} not ready")
        contract.close()
        return False
    
    # Run tests
    results = contract.run_all_tests()
    
    # Print results
    all_passed = True
    for test_name, result in results.items():
        if isinstance(result, dict) and "error" in result:
            print(f"  FAIL: {test_name} - {result['error']}")
            all_passed = False
        else:
            print(f"  PASS: {test_name}")
    
    contract.close()
    
    if all_passed:
        print(f"  All {service_name} contract tests passed")
    else:
        print(f"  Some {service_name} contract tests failed")
    
    return all_passed


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python conformance.py <base_url> <service_name>")
        sys.exit(1)
    
    base_url = sys.argv[1]
    service_name = sys.argv[2]
    
    success = run_contract_test(base_url, service_name)
    sys.exit(0 if success else 1)