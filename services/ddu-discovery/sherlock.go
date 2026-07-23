package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

type sherlockAdapter struct {
	path string
}

func newSherlockAdapter() *sherlockAdapter {
	path := strings.TrimSpace(os.Getenv("SHERLOCK_PATH"))
	if path == "" {
		path = "sherlock"
	}
	return &sherlockAdapter{path: path}
}

func (a *sherlockAdapter) Search(ctx context.Context, username string, sites []string) ([]CandidateAccount, error) {
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		return stubSearch(username), nil
	}
	args := []string{username, "--json", "--timeout", "15"}
	if len(sites) > 0 {
		args = append(args, "--site", strings.Join(sites, ","))
	}
	cmd := exec.CommandContext(ctx, a.path, args...)
	cmd.Stderr = os.Stderr
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("sherlock execution failed: %w", err)
	}
	return parseSherlockOutput(output, username)
}

func parseSherlockOutput(output []byte, username string) ([]CandidateAccount, error) {
	var results map[string]struct {
		URL    string `json:"url"`
		Status string `json:"status"`
	}
	if err := json.Unmarshal(output, &results); err != nil {
		return nil, fmt.Errorf("sherlock output parse failed: %w", err)
	}
	var accounts []CandidateAccount
	for platform, result := range results {
		if result.URL == "" {
			continue
		}
		accounts = append(accounts, CandidateAccount{
			Platform:   platform,
			ProfileURL: result.URL,
			Username:   username,
		})
	}
	return accounts, nil
}

func stubSearch(username string) []CandidateAccount {
	return []CandidateAccount{
		{Platform: "GitHub", ProfileURL: fmt.Sprintf("https://github.com/%s", username), Username: username},
		{Platform: "Twitter", ProfileURL: fmt.Sprintf("https://twitter.com/%s", username), Username: username},
		{Platform: "Instagram", ProfileURL: fmt.Sprintf("https://instagram.com/%s", username), Username: username},
	}
}
