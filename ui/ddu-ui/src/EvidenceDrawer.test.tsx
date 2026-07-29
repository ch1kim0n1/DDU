import {fireEvent, render, screen} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

import {EvidenceDrawer} from "./EvidenceDrawer";
import type {Finding} from "./mirror-types";

const finding: Finding = {
  contract_version: "1.0.0",
  id: "f1",
  parent_id: "f_seed",
  hop_depth: 1,
  type: "account",
  label: "Test account",
  detail: "A redacted account finding",
  verification_state: "likely",
  confidence: 0.8,
  severity: "high",
  severity_score: 0.8,
  severity_base: 0.7,
  reversible: true,
  remediation: {action: "Lock the account", effort: "low"},
  platform: "github",
  source: "mock:generator",
  method: "test",
  subject_ref: "subject:test",
  origin: "agent",
  evidence: [{kind: "kv", k: "handle", v: "@r***", reveal_token: "tok", redacted: true}],
  attack_path_ids: [],
  timestamp: new Date().toISOString(),
};

describe("EvidenceDrawer", () => {
  it("shows redacted evidence and closes", () => {
    const onClose = vi.fn();
    render(
      <EvidenceDrawer
        attribution={[]}
        finding={finding}
        onClose={onClose}
        onReject={vi.fn()}
        rejecting={false}
        score={{
          score: 40,
          band: "elevated",
          persona: "scammer",
          contributing_findings: 1,
          suppressed_findings: 0,
          irreversible_share: 0.2,
          top_drivers: [],
          by_severity: {info: 0, low: 0, medium: 0, high: 1, critical: 0},
        }}
        sessionId="sess_test"
      />,
    );
    expect(screen.getByText("Test account")).toBeInTheDocument();
    expect(screen.getByText("@r***")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close evidence drawer"));
    expect(onClose).toHaveBeenCalled();
  });
});
