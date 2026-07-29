import {useRef, useState} from "react";

import {useFocusTrap} from "./focusTrap";
import {mirrorApi} from "./mirror-api";
import type {VoiceTurnResult} from "./mirror-types";

async function blobToBase64(blob: Blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function VoicePanel({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [recording, setRecording] = useState(false);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<VoiceTurnResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [micAvailable, setMicAvailable] = useState(() =>
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia),
  );
  const speechSupported = typeof window !== "undefined" && "speechSynthesis" in window;
  useFocusTrap(panelRef, true, onClose, closeRef);

  function play(resultData: VoiceTurnResult) {
    if (resultData.audio_base64 && resultData.audio_mime) {
      const audio = new Audio(
        `data:${resultData.audio_mime};base64,${resultData.audio_base64}`,
      );
      void audio.play();
      return;
    }
    if (speechSupported) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(resultData.answer));
    }
  }

  async function submit(input: {
    transcript?: string;
    audioBase64?: string;
    mimeType?: string;
    mode?: string;
  }) {
    setBusy(true);
    setError("");
    try {
      const next = await mirrorApi.voiceTurn(sessionId, input);
      setResult(next);
      play(next);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Voice turn failed";
      if (message.includes("503") || message.toLowerCase().includes("unavailable")) {
        setError(
          "Voice assistant is temporarily unavailable. You can still type your question.",
        );
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {type: recorder.mimeType});
        stream.getTracks().forEach((track) => track.stop());
        void blobToBase64(blob).then((audioBase64) =>
          submit({audioBase64, mimeType: recorder.mimeType}),
        );
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setMicAvailable(false);
      setError("Microphone permission was not granted. Type a question instead.");
    }
  }

  return (
    <aside
      ref={panelRef}
      className="voice-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Voice assistant"
    >
      <header>
        <div>
          <span className="voice-wave" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <div>
            <strong>Mirror voice</strong>
            <small>PII-scrubbed, session grounded</small>
          </div>
        </div>
        <button
          ref={closeRef}
          className="icon-button"
          onClick={onClose}
          aria-label="Close voice panel"
        >
          X
        </button>
      </header>
      <div className="voice-body">
        <div className="voice-privacy">
          <strong>Your voice is not the prompt.</strong>
          <p>
            ElevenLabs transcribes the clip. DDU then removes identifiers before
            any text reaches the reasoning or speech layer.
          </p>
        </div>
        {micAvailable ? (
          <button
            className={`record-button ${recording ? "recording" : ""}`}
            disabled={busy}
            onClick={() => void toggleRecording()}
            type="button"
          >
            <span />
            {recording ? "Stop & scrub" : busy ? "Grounding answer..." : "Ask with voice"}
          </button>
        ) : (
          <p className="inline-error" role="status">
            Microphone is not available in this browser. Use the text input below.
          </p>
        )}
        <div className="voice-divider">
          <span>or type locally</span>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!question.trim()) return;
            void submit({transcript: question.trim()});
          }}
        >
          <textarea
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Which exposure should I fix first?"
            rows={3}
            value={question}
          />
          <button disabled={busy || !question.trim()} type="submit">
            Ask the graph
          </button>
        </form>
        <button
          className="narrate-button"
          disabled={busy}
          onClick={() => void submit({mode: "narrate"})}
          type="button"
        >
          Narrate current severity list
        </button>
        {error && <p className="inline-error">{error}</p>}
        {result && (
          <div className="voice-answer" aria-live="polite">
            <div>
              <span>{result.offline ? "LOCAL FALLBACK" : "GROUNDED RESPONSE"}</span>
              <span>
                {Object.keys(result.replacements).length
                  ? `${Object.values(result.replacements).reduce((a, b) => a + b, 0)} identifiers scrubbed`
                  : "No PII detected"}
              </span>
            </div>
            {result.transcript && <q>{result.transcript}</q>}
            <p>{result.answer}</p>
            {!speechSupported && !result.audio_base64 ? (
              <small>Audio playback is not supported in this browser.</small>
            ) : null}
            <small>
              Grounded in {result.grounded_finding_ids.length} live, non-rejected
              findings.
            </small>
          </div>
        )}
      </div>
    </aside>
  );
}
