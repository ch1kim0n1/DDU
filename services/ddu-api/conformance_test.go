package main

import (
	"testing"

	dducontracts "github.com/ddu/ddu-contracts"
)

func TestServiceContract(t *testing.T) {
	// This test assumes the service is running on localhost:8001
	// For CI testing, the service should be started before running tests
	contract := dducontracts.NewServiceContract("http://localhost:8001")
	
	// Wait for service to be ready (with timeout)
	if err := contract.WaitForService(30 * 1000000000); err != nil {
		t.Skipf("Service not ready: %v (skip in CI if service not running)", err)
	}
	
	// Run all contract tests
	contract.RunAllContractTests(t)
}