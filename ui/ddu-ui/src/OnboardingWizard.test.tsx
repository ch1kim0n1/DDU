import {fireEvent, render, screen, within} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

import {OnboardingWizard} from "./OnboardingWizard";

function addEmail(value: string) {
  const email = screen.getByPlaceholderText("you@example.com");
  fireEvent.change(email, {target: {value}});
  const row = email.closest(".wizard-input-row");
  if (!row) throw new Error("missing email row");
  fireEvent.click(within(row as HTMLElement).getByRole("button", {name: "Add"}));
}

describe("OnboardingWizard", () => {
  it("rejects invalid email and requires consent + legal ack", () => {
    const onComplete = vi.fn();
    render(
      <OnboardingWizard busy={false} error="" onCancel={vi.fn()} onComplete={onComplete} />,
    );

    addEmail("not-an-email");
    expect(screen.queryByText("not-an-email")).toBeNull();
    expect(screen.getByText(/valid email/i)).toBeInTheDocument();

    addEmail("you@example.com");
    expect(screen.getByText("you@example.com")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: "Continue"}));
    fireEvent.click(screen.getByRole("button", {name: "Continue"}));
    fireEvent.click(screen.getByRole("button", {name: "Continue"}));

    const start = screen.getByRole("button", {name: "Start real scan"});
    expect(start).toBeDisabled();

    fireEvent.click(
      screen.getByLabelText(
        /I confirm that I am 18 or older and I consent to scanning my own public footprint/i,
      ),
    );
    fireEvent.click(
      screen.getByLabelText(/I have read and agree to the Privacy Policy and Terms of Service/i),
    );
    expect(start).not.toBeDisabled();
    fireEvent.click(start);
    expect(onComplete).toHaveBeenCalled();
  });

  it("supports persona selection and back navigation", () => {
    render(
      <OnboardingWizard busy={false} error="" onCancel={vi.fn()} onComplete={vi.fn()} />,
    );
    addEmail("a@b.co");
    fireEvent.click(screen.getByRole("button", {name: "Continue"}));
    fireEvent.click(screen.getByLabelText(/Personal safety/i));
    fireEvent.click(screen.getByRole("button", {name: "Back"}));
    // The step-1 headline. "Step 1 of 4" appears twice — once visibly and once
    // in the sr-only live region — so matching on the marker is ambiguous.
    expect(screen.getByText("Which accounts are yours?")).toBeInTheDocument();
  });
});
