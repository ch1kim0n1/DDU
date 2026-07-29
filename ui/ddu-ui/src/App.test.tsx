import {render, screen} from "@testing-library/react";
import {describe, expect, it, vi, beforeEach} from "vitest";

vi.mock("./mirror-api", () => ({
  mirrorApi: {
    health: vi.fn(async () => ({state: "HEALTHY", service: "ddu-mirror-intel"})),
    versionz: vi.fn(async () => ({
      service: "ddu-mirror-intel",
      service_version: "0.0.0",
      tool_version: "1.0.0",
    })),
    providers: vi.fn(async () => ({
      anthropic: "not_configured",
      openai: "not_configured",
      local: "available",
      llm: "degraded",
      elevenlabs: "not_configured",
      redis: "disabled",
    })),
    createSession: vi.fn(async () => ({
      session_id: "sess_test",
      snapshot: {
        session_id: "sess_test",
        contract_version: "1.0.0",
        persona: "scammer",
        findings: [],
        attack_paths: [],
        attribution: [],
        score: {
          score: 0,
          band: "low",
          persona: "scammer",
          contributing_findings: 0,
          suppressed_findings: 0,
          irreversible_share: 0,
          top_drivers: [],
          by_severity: {},
        },
        pending_proposals: [],
        action_log_tail: [],
      },
    })),
    plan: vi.fn(async () => ({proposals: []})),
    snapshot: vi.fn(async () => {
      throw new Error("missing");
    }),
  },
  websocketURL: () => "ws://localhost/intel/ws/x",
  SessionExpiredError: class extends Error {},
  RateLimitError: class extends Error {},
}));

import App from "./App";

describe("App", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("boots mock mode and shows the shell or boot screen", async () => {
    render(<App />);
    expect(
      screen.getByText(/Establishing an ephemeral Mirror session|The experience is built|DDU \/ MIRROR/i),
    ).toBeInTheDocument();
  });
});
