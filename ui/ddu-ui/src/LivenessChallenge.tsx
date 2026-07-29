/**
 * Engineer C to A drop-in: client-side liveness challenge.
 *
 * MediaPipe FaceLandmarker runs in the browser. Only one verified frame is
 * uploaded after the challenge passes - a real privacy property.
 *
 * Props keep this mountable inside Engineer A's consent flow without
 * coupling to the rest of the Mirror shell.
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

export function LivenessChallenge({
  sessionId,
  onPassed,
  onFailed,
  onSkipped,
  className,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [challenge, setChallenge] = useState<LivenessChallengeKind | null>(null);
  const [challengeId, setChallengeId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [error, setError] = useState("");
  const [ttl, setTtl] = useState<number | null>(null);
  const [mediapipeReady, setMediapipeReady] = useState(false);
  const [cameraHint, setCameraHint] = useState(
    "Click below to allow camera access. The video never leaves your browser.",
  );
  const [biometricConsent, setBiometricConsent] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef(0);
  const landmarkerRef = useRef<{
    detectForVideo: (video: HTMLVideoElement, ts: number) => {faceBlendshapes?: Array<{categories: Array<{categoryName: string; score: number}>}>; faceLandmarks?: Array<Array<{x: number; y: number; z: number}>>};
    close: () => void;
  } | null>(null);
  const progressRef = useRef({blinks: 0, yawSamples: 0});

  const stopCamera = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
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
      outputFacialTransformationMatrixes: true,
    });
    landmarkerRef.current = landmarker;
    setMediapipeReady(true);
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
    const frame = passed ? captureFrame() : null;
    stopCamera();
    try {
      const result = await mirrorApi.livenessComplete(sessionId, challengeId, passed, frame);
      if (result.passed) {
        setPhase("passed");
        setTtl(result.template_ttl_seconds_remaining);
        onPassed?.({
          challengeId,
          ttlSeconds: result.template_ttl_seconds_remaining,
        });
      } else {
        setPhase("failed");
        onFailed?.();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Liveness complete failed");
      setPhase("failed");
      onFailed?.();
    }
  }

  function evaluateLandmarkFrame(
    kind: LivenessChallengeKind,
    result: {
      faceBlendshapes?: Array<{categories: Array<{categoryName: string; score: number}>}>;
      faceLandmarks?: Array<Array<{x: number; y: number; z: number}>>;
    },
  ) {
    const shapes = result.faceBlendshapes?.[0]?.categories || [];
    const byName = Object.fromEntries(shapes.map((c) => [c.categoryName, c.score]));
    const blinkScore = Math.max(byName["eyeBlinkLeft"] || 0, byName["eyeBlinkRight"] || 0);

    if (kind === "blink") {
      if (blinkScore > 0.55) progressRef.current.blinks += 1;
      if (progressRef.current.blinks >= 2) void complete(true);
      return;
    }

    const nose = result.faceLandmarks?.[0]?.[1];
    if (!nose) return;
    // Rough yaw proxy: nose x offset from centre.
    const yaw = nose.x - 0.5;
    if (kind === "turn_left" && yaw < -0.08) progressRef.current.yawSamples += 1;
    if (kind === "turn_right" && yaw > 0.08) progressRef.current.yawSamples += 1;
    if (progressRef.current.yawSamples >= 8) void complete(true);
  }

  async function start() {
    if (!biometricConsent) {
      setError("Confirm biometric consent before starting the camera.");
      return;
    }
    setError("");
    setPhase("starting");
    progressRef.current = {blinks: 0, yawSamples: 0};
    try {
      if (navigator.permissions?.query) {
        try {
          const status = await navigator.permissions.query({
            name: "camera" as PermissionName,
          });
          if (status.state === "denied") {
            setCameraHint(
              "Camera access is blocked. Enable it in your browser settings (click the camera icon in the address bar) and try again.",
            );
            setPhase("idle");
            setError(
              "Camera access is blocked. Enable it in your browser settings (click the camera icon in the address bar) and try again.",
            );
            return;
          }
          if (status.state === "prompt") {
            setCameraHint(
              "Click below to allow camera access. The video never leaves your browser.",
            );
          }
        } catch {
          // permissions.query for camera is not supported everywhere
        }
      }
      const started = await mirrorApi.livenessStart(sessionId);
      setChallengeId(started.challenge_id);
      setChallenge(started.challenge as LivenessChallengeKind);
      setInstructions(started.instructions);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {facingMode: "user", width: {ideal: 640}, height: {ideal: 480}},
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      try {
        const landmarker = await ensureLandmarker();
        setPhase("running");
        const tick = () => {
          const video = videoRef.current;
          if (!video || video.readyState < 2) {
            rafRef.current = requestAnimationFrame(tick);
            return;
          }
          const detection = landmarker.detectForVideo(video, performance.now());
          if (started.challenge) {
            evaluateLandmarkFrame(started.challenge as LivenessChallengeKind, detection);
          }
          rafRef.current = requestAnimationFrame(tick);
        };
        rafRef.current = requestAnimationFrame(tick);
      } catch {
        // Camera works; MediaPipe unavailable - operator can force pass/fail for demo.
        setMediapipeReady(false);
        setPhase("running");
        setError(
          "MediaPipe unavailable in this browser - use Pass/Fail controls (camera still local).",
        );
      }
    } catch (reason) {
      stopCamera();
      setPhase("idle");
      const err = reason as DOMException;
      if (err?.name === "NotAllowedError") {
        setError(
          "Camera access is blocked. Enable it in your browser settings (click the camera icon in the address bar) and try again.",
        );
      } else if (err?.name === "NotFoundError") {
        setError("No camera detected on this device.");
      } else {
        setError(reason instanceof Error ? reason.message : "Could not start liveness");
      }
    }
  }

  async function skip() {
    stopCamera();
    try {
      await mirrorApi.livenessSkip(sessionId);
      setPhase("skipped");
      onSkipped?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Skip failed");
    }
  }

  return (
    <div className={`liveness-challenge ${className || ""}`}>
      <header>
        <p className="eyebrow">Biometric step-up, optional</p>
        <h3>Live face check</h3>
        <p>
          Your face data is processed locally in your browser and never uploaded
          as a video stream. It is destroyed when you close this panel. Only one
          verified frame may upload after you pass.
        </p>
        <p className="liveness-hint">{cameraHint}</p>
        <label className="liveness-consent">
          <input
            type="checkbox"
            checked={biometricConsent}
            onChange={(e) => setBiometricConsent(e.target.checked)}
          />
          I consent to biometric processing for liveness verification
        </label>
      </header>

      <div className="liveness-stage">
        <video aria-label="Liveness camera preview" autoPlay muted playsInline ref={videoRef} />
        <canvas hidden ref={canvasRef} />
        {phase === "running" && challenge ? (
          <div className="liveness-prompt">
            <strong>{challenge.replace("_", " ")}</strong>
            <span>{instructions}</span>
          </div>
        ) : null}
      </div>

      <div className="liveness-actions">
        {phase === "idle" || phase === "failed" ? (
          <button onClick={() => void start()} type="button">
            {phase === "failed" ? "Try again" : "Start challenge"}
          </button>
        ) : null}
        {phase === "running" && !mediapipeReady ? (
          <>
            <button className="approve" onClick={() => void complete(true)} type="button">
              Simulate pass
            </button>
            <button onClick={() => void complete(false)} type="button">
              Simulate fail
            </button>
          </>
        ) : null}
        {phase !== "skipped" && phase !== "passed" ? (
          <button onClick={() => void skip()} type="button">
            Skip face path
          </button>
        ) : null}
      </div>

      {phase === "passed" ? (
        <p className="liveness-ok">
          Passed. Ephemeral template TTL: {ttl ?? "-"}s remaining.
        </p>
      ) : null}
      {phase === "failed" ? <p className="liveness-fail">Challenge failed - no frame kept.</p> : null}
      {phase === "skipped" ? (
        <p className="liveness-skip">Face path skipped. No dangling biometric state.</p>
      ) : null}
      {error ? <p className="liveness-error">{error}</p> : null}
    </div>
  );
}
