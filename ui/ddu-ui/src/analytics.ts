/** Privacy-friendly analytics shim (Plausible-compatible). Never send PII. */

type EventName =
  | "session_started"
  | "proposal_approved"
  | "proposal_rejected"
  | "voice_turn"
  | "vision_analyzed"
  | "wipe_completed"
  | "wizard_completed"
  | "wizard_abandoned"
  | "wizard_step";

declare global {
  interface Window {
    plausible?: (event: string, options?: {props?: Record<string, string | number | boolean>}) => void;
  }
}

export function track(event: EventName, props?: Record<string, string | number | boolean>) {
  try {
    window.plausible?.(event, props ? {props: props} : undefined);
  } catch {
    // analytics must never break the product
  }
}
