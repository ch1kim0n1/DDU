/**
 * Live face check — client-side liveness challenge.
 *
 * Engineer C's original component, rewritten to fix a freeze and to show the
 * scan happening. MediaPipe FaceMesh runs entirely in the browser; the video
 * stream never leaves the device, and at most one still frame uploads after the
 * challenge passes.
 *
 * ─── Why it used to break on "turn left" ─────────────────────────────────────
 *
 * Three faults compounded:
 *
 * 1. **Inverted yaw.** The preview is mirrored for a natural selfie view
 *    (`transform: scaleX(-1)`), but detection reads the *raw* video element. In
 *    raw coordinates, turning your head to your own left moves your nose toward
 *    +x. The old check wanted x to decrease, so "turn left" could never be
 *    satisfied — you turned further and further until your face left the frame.
 *
 * 2. **A render loop that could not survive an error.** `requestAnimationFrame`
 *    was scheduled *after* `detectForVideo`, so the first throw — which the
 *    over-rotation above reliably caused — stopped the loop permanently. The
 *    preview froze with no message. The next frame is now scheduled *first*, so
 *    nothing can kill the loop.
 *
 * 3. **Non-monotonic timestamps.** MediaPipe's VIDEO mode rejects a timestamp
 *    that is not strictly greater than the last one, and `performance.now()` can
 *    repeat within a frame. That threw, which triggered fault 2. Timestamps are
 *    now clamped upward and frames are skipped when the video has not advanced.
 *
 * Yaw is also measured relative to the eye corners rather than from raw nose x,
 * so sliding your face sideways no longer counts as rotating it, and the hold is
 * timed rather than counted in frames (8 frames was ~130ms — twitchy).
 */

import {useCallback, useEffect, useRef, useState} from "react";

import {mirrorApi} from "./mirror-api";

export type LivenessChallengeKind = "blink" | "turn_left" | "turn_right";

type Props = {
  sessionId: string;
  onPassed?: (info: {challengeId: string; ttlSeconds: number | null}) => void;
  onFailed?: () => void;
  onSkipped?: () => void;
  className?: string;
};

type Phase = "idle" | "starting" | "running" | "passed" | "failed" | "skipped";

type Landmark = {x: number; y: number; z: number};
type Detection = {
  faceBlendshapes?: Array<{categories: Array<{categoryName: string; score: number}>}>;
  faceLandmarks?: Landmark[][];
};

/** MediaPipe FaceMesh indices. 33/263 are the outer eye corners, 1 is the nose tip. */
const EYE_R = 33;
const EYE_L = 263;
const NOSE = 1;

/** Sustained hold required for a head turn, in milliseconds. */
const HOLD_MS = 550;
/** Blinks required. */
const BLINKS_NEEDED = 2;

/**
 * Translation- and scale-invariant yaw: where the nose sits between the eyes.
 *
 * Module-level and pure so the direction can be asserted in a test. It is worth
 * the export: the sign of this comparison was the actual bug — "turn left" could
 * never complete, so people kept turning further until their face left frame,
 * and the exception that followed killed the render loop. A synthetic camera
 * feed cannot catch a regression here, so a test has to.
 */
export function yawRatio(landmarks: Landmark[]): number | null {
  const right = landmarks[EYE_R];
  const left = landmarks[EYE_L];
  const nose = landmarks[NOSE];
  if (!right || !left || !nose) return null;
  const span = left.x - right.x;
  if (Math.abs(span) < 1e-4) return null;
  // 0.5 looking straight ahead; drifts toward 0 or 1 as the head rotates.
  return (nose.x - right.x) / span;
}

/**
 * Raw video coordinates — NOT the mirrored preview the user sees.
 *
 * The preview is flipped with `scaleX(-1)` so it reads as a mirror, but
 * detection runs on the unflipped feed. There, turning your head to your own
 * LEFT swings the nose toward +x, so a left turn is a HIGHER ratio.
 */
export function isTurned(kind: LivenessChallengeKind, ratio: number): boolean {
  return kind === "turn_left" ? ratio > 0.62 : ratio < 0.38;
}

const PROMPT: Record<LivenessChallengeKind, string> = {
  blink: "Blink twice, slowly",
  turn_left: "Slowly turn your head left",
  turn_right: "Slowly turn your head right",
};

export function LivenessChallenge({
  sessionId,
  onPassed,
  onFailed,
  onSkipped,
  className,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [challenge, setChallenge] = useState<LivenessChallengeKind | null>(null);
  const [challengeId, setChallengeId] = useState("");
  const [error, setError] = useState("");
  const [ttl, setTtl] = useState<number | null>(null);
  const [meshReady, setMeshReady] = useState(false);
  const [faceFound, setFaceFound] = useState(false);
  const [progress, setProgress] = useState(0);
  const [biometricConsent, setBiometricConsent] = useState(false);
  const [hint, setHint] = useState(
    "Your camera turns on only after you consent, and the video never leaves this device.",
  );

  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);
  const landmarkerRef = useRef<{
    detectForVideo: (video: HTMLVideoElement, ts: number) => Detection;
    close: () => void;
  } | null>(null);

  // Loop bookkeeping that must not trigger re-renders.
  const lastVideoTime = useRef(-1);
  const lastStamp = useRef(0);
  const consecutiveErrors = useRef(0);
  const blinkRef = useRef({count: 0, closed: false});
  const holdRef = useRef(0);
  const doneRef = useRef(false);

  const stopCamera = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    landmarkerRef.current?.close();
    landmarkerRef.current = null;
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  async function ensureLandmarker() {
    if (landmarkerRef.current) return landmarkerRef.current;
    const vision = await import("@mediapipe/tasks-vision");
    const fileset = await vision.FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm",
    );
    const landmarker = await vision.FaceLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath:
          "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        delegate: "GPU",
      },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFaceBlendshapes: true,
    });
    landmarkerRef.current = landmarker;
    setMeshReady(true);
    return landmarker;
  }

  function captureFrame(): Blob | null {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.videoWidth === 0) return null;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    const binary = atob(dataUrl.split(",")[1] || "");
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], {type: "image/jpeg"});
  }

  async function complete(passed: boolean) {
    // Guard against the loop firing completion twice before rAF is cancelled.
    if (doneRef.current) return;
    doneRef.current = true;

    const frame = passed ? captureFrame() : null;
    stopCamera();
    setProgress(passed ? 1 : 0);
    try {
      const result = await mirrorApi.livenessComplete(sessionId, challengeId, passed, frame);
      if (result.passed) {
        setPhase("passed");
        setTtl(result.template_ttl_seconds_remaining);
        onPassed?.({challengeId, ttlSeconds: result.template_ttl_seconds_remaining});
      } else {
        setPhase("failed");
        onFailed?.();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not finish the check");
      setPhase("failed");
      onFailed?.();
    }
  }

  /** Draws the landmark dots over the preview — the visible "scan". */
  function paintMesh(landmarks: Landmark[] | undefined) {
    const overlay = overlayRef.current;
    const video = videoRef.current;
    if (!overlay || !video) return;
    const w = overlay.clientWidth;
    const h = overlay.clientHeight;
    if (overlay.width !== w || overlay.height !== h) {
      overlay.width = w;
      overlay.height = h;
    }
    const ctx = overlay.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    if (!landmarks) return;

    // The preview is mirrored in CSS, so mirror the overlay to match — otherwise
    // the dots sit on the opposite side of the face from the features they track.
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.fillStyle = "rgba(124, 231, 255, 0.85)";
    for (let i = 0; i < landmarks.length; i += 2) {
      const point = landmarks[i];
      ctx.beginPath();
      ctx.arc(point.x * w, point.y * h, 1.05, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function evaluate(kind: LivenessChallengeKind, detection: Detection, dtMs: number) {
    const landmarks = detection.faceLandmarks?.[0];
    paintMesh(landmarks);

    if (!landmarks) {
      setFaceFound(false);
      holdRef.current = 0;
      setProgress(0);
      return;
    }
    setFaceFound(true);

    if (kind === "blink") {
      const shapes = detection.faceBlendshapes?.[0]?.categories || [];
      const score = Math.max(
        ...shapes
          .filter((c) => c.categoryName === "eyeBlinkLeft" || c.categoryName === "eyeBlinkRight")
          .map((c) => c.score),
        0,
      );
      // Count a blink on the closed->open edge rather than every closed frame,
      // otherwise one slow blink counts as several.
      if (score > 0.5 && !blinkRef.current.closed) blinkRef.current.closed = true;
      else if (score < 0.25 && blinkRef.current.closed) {
        blinkRef.current.closed = false;
        blinkRef.current.count += 1;
      }
      setProgress(Math.min(1, blinkRef.current.count / BLINKS_NEEDED));
      if (blinkRef.current.count >= BLINKS_NEEDED) void complete(true);
      return;
    }

    const ratio = yawRatio(landmarks);
    if (ratio === null) return;

    if (isTurned(kind, ratio)) holdRef.current += dtMs;
    else holdRef.current = Math.max(0, holdRef.current - dtMs * 1.5);

    setProgress(Math.min(1, holdRef.current / HOLD_MS));
    if (holdRef.current >= HOLD_MS) void complete(true);
  }

  async function start() {
    if (!biometricConsent) {
      setError("Please confirm biometric consent before the camera starts.");
      return;
    }
    setError("");
    setPhase("starting");
    setProgress(0);
    setFaceFound(false);
    blinkRef.current = {count: 0, closed: false};
    holdRef.current = 0;
    doneRef.current = false;
    lastVideoTime.current = -1;
    lastStamp.current = 0;
    consecutiveErrors.current = 0;

    try {
      const started = await mirrorApi.livenessStart(sessionId);
      setChallengeId(started.challenge_id);
      const kind = started.challenge as LivenessChallengeKind;
      setChallenge(kind);

      const stream = await navigator.mediaDevices.getUserMedia({
        video: {facingMode: "user", width: {ideal: 640}, height: {ideal: 480}},
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      let landmarker: NonNullable<typeof landmarkerRef.current>;
      try {
        landmarker = await ensureLandmarker();
      } catch {
        setMeshReady(false);
        setPhase("running");
        setHint("Face tracking is unavailable in this browser. The camera is still local to your device.");
        return;
      }

      setPhase("running");
      setHint("Hold your face inside the circle.");

      let prev = performance.now();
      const tick = () => {
        // Scheduled FIRST, deliberately. If anything below throws, the loop
        // still has its next frame queued — the original ordering meant a single
        // detection error froze the preview permanently with no message.
        rafRef.current = requestAnimationFrame(tick);
        if (doneRef.current) return;

        const video = videoRef.current;
        if (!video || video.readyState < 2 || video.videoWidth === 0) return;

        // MediaPipe re-runs on an unchanged frame for no benefit, and its VIDEO
        // mode rejects repeated timestamps.
        if (video.currentTime === lastVideoTime.current) return;
        lastVideoTime.current = video.currentTime;

        const now = performance.now();
        const dtMs = Math.min(120, now - prev);
        prev = now;

        // Strictly increasing, which VIDEO mode requires.
        const stamp = now <= lastStamp.current ? lastStamp.current + 1 : now;
        lastStamp.current = stamp;

        try {
          const detection = landmarker.detectForVideo(video, stamp);
          consecutiveErrors.current = 0;
          evaluate(kind, detection, dtMs);
        } catch (reason) {
          consecutiveErrors.current += 1;
          // Transient failures are normal (a frame arrives mid-resize, the GPU
          // context blips). Only surface a sustained run of them.
          if (consecutiveErrors.current === 30) {
            setError(
              reason instanceof Error
                ? `Face tracking keeps failing: ${reason.message}`
                : "Face tracking keeps failing.",
            );
          }
        }
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch (reason) {
      stopCamera();
      setPhase("idle");
      const err = reason as DOMException;
      if (err?.name === "NotAllowedError") {
        setError(
          "Camera access is blocked. Allow it from the camera icon in your address bar, then try again.",
        );
      } else if (err?.name === "NotFoundError") {
        setError("No camera found on this device.");
      } else {
        setError(reason instanceof Error ? reason.message : "Could not start the check");
      }
    }
  }

  async function skip() {
    stopCamera();
    doneRef.current = true;
    try {
      await mirrorApi.livenessSkip(sessionId);
      setPhase("skipped");
      onSkipped?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not skip");
    }
  }

  const ringCircumference = 2 * Math.PI * 47;
  const active = phase === "running" || phase === "starting";

  return (
    <div className={`liveness-challenge ${className || ""}`}>
      {/* ── the scan ── */}
      <div className={`face-scan ${active ? "is-active" : ""} ${phase === "passed" ? "is-passed" : ""}`}>
        <div className="face-scan-ring">
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle className="ring-track" cx="50" cy="50" r="47" />
            <circle
              className="ring-progress"
              cx="50"
              cy="50"
              r="47"
              strokeDasharray={ringCircumference}
              strokeDashoffset={ringCircumference * (1 - progress)}
            />
          </svg>
        </div>

        <div className="face-scan-window">
          <video aria-label="Camera preview" autoPlay muted playsInline ref={videoRef} />
          <canvas className="face-scan-mesh" ref={overlayRef} />
          {phase === "idle" ? (
            <div className="face-scan-idle">
              <span aria-hidden="true">◎</span>
              <p>Camera off</p>
            </div>
          ) : null}
          {phase === "passed" ? (
            <div className="face-scan-done" role="status">
              <span aria-hidden="true">✓</span>
            </div>
          ) : null}
        </div>
      </div>

      {/* ── instruction ── */}
      {phase === "running" && challenge ? (
        <div className={`face-prompt ${faceFound ? "" : "is-searching"}`} role="status">
          <span className="dot" aria-hidden="true" />
          <strong>{faceFound ? PROMPT[challenge] : "Looking for your face…"}</strong>
          <em>{Math.round(progress * 100)}%</em>
        </div>
      ) : null}

      {phase === "starting" ? (
        <div className="face-prompt" role="status">
          <span className="dot" aria-hidden="true" />
          <strong>Starting the camera…</strong>
        </div>
      ) : null}

      <p className="liveness-hint">{hint}</p>

      <label className="liveness-consent">
        <input
          checked={biometricConsent}
          onChange={(event) => setBiometricConsent(event.target.checked)}
          type="checkbox"
        />
        I consent to biometric processing for this liveness check
      </label>

      <div className="liveness-actions">
        {phase === "idle" || phase === "failed" ? (
          <button disabled={!biometricConsent} onClick={() => void start()} type="button">
            {phase === "failed" ? "Try again" : "Start face check"}
          </button>
        ) : null}
        {phase === "running" && !meshReady ? (
          <button className="approve" onClick={() => void complete(true)} type="button">
            Confirm manually
          </button>
        ) : null}
        {phase !== "skipped" && phase !== "passed" ? (
          <button onClick={() => void skip()} type="button">
            Skip face path
          </button>
        ) : null}
      </div>

      {phase === "passed" ? (
        <p className="liveness-ok">
          Verified. Face template is held for {ttl ?? "-"}s, then destroyed.
        </p>
      ) : null}
      {phase === "failed" ? (
        <p className="liveness-fail">Check did not pass. No frame was kept.</p>
      ) : null}
      {phase === "skipped" ? (
        <p className="liveness-skip">
          Face path skipped. This session is marked email-only assurance.
        </p>
      ) : null}
      {error ? <p className="liveness-error">{error}</p> : null}
    </div>
  );
}
