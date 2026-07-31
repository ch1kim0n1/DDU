/**
 * Engineer C photo intelligence panel - demo asset one-click + file upload.
 */

import {useEffect, useState} from "react";

import {mirrorApi, type VisionAnalyzeResult, type VisionDemoAsset} from "./mirror-api";
import type {Finding, SessionSnapshot} from "./mirror-types";
import {LivenessChallenge} from "./LivenessChallenge";

export type VisionViewCue = "scene" | "map";

type Props = {
  sessionId: string;
  onSnapshot: (snapshot: SessionSnapshot) => void;
  /** After ingest: jump the main workspace to 3D or Map and select a finding. */
  onPayoff?: (info: {
    preferredView: VisionViewCue;
    focusFinding: Finding | null;
    accepted: Finding[];
  }) => void;
  busy: boolean;
  setBusy: (label: string) => void;
  setError: (message: string) => void;
};

function preferredViewFor(findings: Finding[]): VisionViewCue {
  const spatial = findings.some(
    (f) => f.type === "gps_exposure" || f.type === "location_inference",
  );
  return spatial ? "map" : "scene";
}

function focusFinding(findings: Finding[]): Finding | null {
  if (!findings.length) return null;
  return [...findings].sort((a, b) => b.severity_score - a.severity_score)[0] || null;
}

export function VisionPanel({
  sessionId,
  onSnapshot,
  onPayoff,
  busy,
  setBusy,
  setError,
}: Props) {
  const [demos, setDemos] = useState<VisionDemoAsset[]>([]);
  const [last, setLast] = useState<VisionAnalyzeResult | null>(null);
  const [showLiveness, setShowLiveness] = useState(false);
  const [preview, setPreview] = useState<{face_count: number; advice: string} | null>(
    null,
  );
  const [cue, setCue] = useState<{
    count: number;
    preferredView: VisionViewCue;
    focus: Finding | null;
    accepted: Finding[];
  } | null>(null);
  const [faceConfigured, setFaceConfigured] = useState(true);
  const [objectDetectionOnline, setObjectDetectionOnline] = useState(true);

  useEffect(() => {
    void mirrorApi.visionDemos().then((payload) => setDemos(payload.assets)).catch(() => {
      /* panel stays usable for raw upload */
    });
    void mirrorApi
      .health()
      .then((payload) => {
        const deps = (payload as {dependencies?: Record<string, string>}).dependencies || {};
        if (deps.compreface === "offline" || deps.compreface === "unconfigured") {
          setFaceConfigured(false);
        }
        if (deps.vision === "degraded" || deps.grounded_sam === "offline") {
          setObjectDetectionOnline(false);
        }
      })
      .catch(() => {
        setObjectDetectionOnline(false);
      });
  }, []);

  function announcePayoff(accepted: Finding[]) {
    if (!accepted.length) {
      setCue(null);
      return;
    }
    const preferred = preferredViewFor(accepted);
    const focus = focusFinding(accepted);
    setCue({count: accepted.length, preferredView: preferred, focus, accepted});
    onPayoff?.({preferredView: preferred, focusFinding: focus, accepted});
  }

  async function analyzeFile(file: File, platform = "upload") {
    if (!file.type.startsWith("image/")) {
      setError("Only image files are supported (JPG, PNG, WebP).");
      return;
    }
    setBusy("vision-analyze");
    setError("");
    try {
      const result = await mirrorApi.visionAnalyze(sessionId, file, platform);
      setLast(result);
      setPreview(result.redaction_preview);
      if (result.snapshot) onSnapshot(result.snapshot);
      announcePayoff(result.accepted || []);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Vision analyze failed";
      if (message.includes("503") || message.toLowerCase().includes("unavailable")) {
        setError(
          "Vision analysis is temporarily unavailable. Your photo has been saved for later processing.",
        );
      } else {
        setError(message);
      }
    } finally {
      setBusy("");
    }
  }

  async function uploadDemo(slug: string, platform?: string | null) {
    setBusy(`demo:${slug}`);
    setError("");
    try {
      const file = await mirrorApi.fetchDemoFile(slug);
      await analyzeFile(file, platform || "upload");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Demo upload failed");
      setBusy("");
    }
  }

  function jump(view: VisionViewCue) {
    if (!cue) return;
    onPayoff?.({
      preferredView: view,
      focusFinding: cue.focus,
      accepted: cue.accepted,
    });
  }

  return (
    <section className="rail-section vision-panel">
      <div className="rail-title">
        <div>
          {/* Team-internal names ("Engineer C") do not belong in the product. */}
          <p className="eyebrow">What your photos give away</p>
          <h2>Photo intelligence</h2>
        </div>
        <span>{demos.length}</span>
      </div>

      <p className="vision-note">
        Demo photos are pre-indexed by file hash (Grounded-SAM-2 + GeoCLIP). EXIF
        is read live. Say so on stage.
      </p>
      {!faceConfigured ? (
        <p className="vision-note" role="status">
          Face recognition is not configured. You can still upload photos for GPS extraction.
        </p>
      ) : null}
      {!objectDetectionOnline ? (
        <p className="vision-note" role="status">
          Object detection is offline. Photos will be stored for later analysis.
        </p>
      ) : null}

      <div className="demo-asset-list">
        {demos.map((demo) => (
          <button
            disabled={Boolean(busy)}
            key={demo.slug}
            onClick={() => void uploadDemo(demo.slug || "", demo.platform)}
            type="button"
          >
            <strong>{demo.label}</strong>
            <small>{demo.description}</small>
          </button>
        ))}
      </div>

      <label className="vision-file">
        <span>Or upload your own</span>
        <input
          accept="image/*"
          disabled={Boolean(busy)}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void analyzeFile(file);
            event.target.value = "";
          }}
          type="file"
        />
      </label>

      {last ? (
        <div className="vision-result">
          <p>
            {last.cache_hit ? "Cache hit" : "Cache miss"}, {last.elapsed_ms}ms
            {last.within_two_seconds ? ", under 2s" : ""}
          </p>
          <p>{last.accepted.length} findings ingested</p>
          {last.disclosures.map((line) => (
            <small key={line}>{line}</small>
          ))}
        </div>
      ) : null}

      {cue ? (
        <div className="vision-payoff-cue" role="status">
          <p>
            <strong>{cue.count} new findings</strong> are in the graph
            {cue.preferredView === "map" ? " - GPS landed on the map." : "."}
          </p>
          <div className="vision-payoff-actions">
            <button
              className={cue.preferredView === "map" ? "approve" : ""}
              onClick={() => jump("map")}
              type="button"
            >
              View map
            </button>
            <button
              className={cue.preferredView === "scene" ? "approve" : ""}
              onClick={() => jump("scene")}
              type="button"
            >
              View 3D
            </button>
            <button onClick={() => setCue(null)} type="button">
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {preview ? (
        <div className="redaction-preview">
          <strong>Redaction preview</strong>
          <p>{preview.advice}</p>
        </div>
      ) : null}

      <button
        className="liveness-toggle"
        onClick={() => setShowLiveness((value) => !value)}
        type="button"
      >
        {showLiveness ? "Hide face step-up" : "Optional face step-up"}
      </button>

      {showLiveness ? (
        <LivenessChallenge
          onSkipped={() => setShowLiveness(false)}
          sessionId={sessionId}
        />
      ) : null}
    </section>
  );
}
