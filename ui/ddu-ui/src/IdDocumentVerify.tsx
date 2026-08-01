/**
 * Demo photo-ID verification — student ID or driver's license upload.
 *
 * Soft assurance path alongside live face: mock OCR on the server, redacted
 * findings in the session graph, session labeled ``id_document``. No face
 * match against the ID photo (stricter path intentionally not shipped).
 */

import {useRef, useState} from "react";

import {mirrorApi} from "./mirror-api";

export type IdDocumentKind = "student_id" | "drivers_license";

type Props = {
  sessionId: string;
  onVerified?: (info: {
    documentKind: IdDocumentKind;
    documentLabel: string;
    disclosures: string[];
  }) => void;
  onSkipped?: () => void;
  className?: string;
};

const KIND_COPY: Record<IdDocumentKind, {title: string; hint: string}> = {
  student_id: {
    title: "Student ID",
    hint: "Upload a clear photo of the front of your student ID card.",
  },
  drivers_license: {
    title: "Driver's license",
    hint: "Upload a clear photo of the front of your driver's license.",
  },
};

export function IdDocumentVerify({sessionId, onVerified, onSkipped, className}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<IdDocumentKind>("drivers_license");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{
    label: string;
    disclosures: string[];
    fields: Record<string, string>;
  } | null>(null);

  function pickFile(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next);
    setPreview(next ? URL.createObjectURL(next) : null);
    setError("");
    setDone(null);
  }

  async function submit() {
    if (!file) {
      setError("Choose a photo of your ID first.");
      return;
    }
    if (!consent) {
      setError("Confirm you consent to processing this ID image for this session.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await mirrorApi.idVerify(sessionId, kind, file);
      setDone({
        label: result.document_label,
        disclosures: result.disclosures || [result.disclosure],
        fields: result.fields || {},
      });
      onVerified?.({
        documentKind: kind,
        documentLabel: result.document_label,
        disclosures: result.disclosures || [result.disclosure],
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not verify ID");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`id-document-verify ${className || ""}`}>
      <div className="id-kind-tabs" role="tablist" aria-label="ID type">
        {(Object.keys(KIND_COPY) as IdDocumentKind[]).map((key) => (
          <button
            aria-selected={kind === key}
            className={kind === key ? "is-on" : ""}
            key={key}
            onClick={() => {
              setKind(key);
              setDone(null);
              setError("");
            }}
            role="tab"
            type="button"
          >
            {KIND_COPY[key].title}
          </button>
        ))}
      </div>

      <p className="id-hint">{KIND_COPY[kind].hint}</p>
      <p className="id-disclosure">
        Demo path: OCR is mocked from the image hash. Fields stay redacted until
        you reveal them. No face-to-ID match runs.
      </p>

      <div className="id-upload-frame">
        {preview ? (
          <img alt="Selected ID preview" src={preview} />
        ) : (
          <div className="id-upload-idle">
            <span aria-hidden="true">▢</span>
            <p>No ID selected</p>
          </div>
        )}
      </div>

      <input
        accept="image/jpeg,image/png,image/webp,image/*"
        hidden
        onChange={(event) => pickFile(event.target.files?.[0] || null)}
        ref={inputRef}
        type="file"
      />

      <label className="liveness-consent">
        <input
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
          type="checkbox"
        />
        I consent to processing this ID image for this Mirror session only
      </label>

      <div className="liveness-actions">
        <button onClick={() => inputRef.current?.click()} type="button">
          {file ? "Choose a different photo" : "Choose ID photo"}
        </button>
        <button
          className="approve"
          disabled={busy || !file || !consent || Boolean(done)}
          onClick={() => void submit()}
          type="button"
        >
          {busy ? "Checking…" : done ? "Verified" : "Verify with this ID"}
        </button>
        {onSkipped ? (
          <button
            disabled={busy}
            onClick={() => onSkipped()}
            type="button"
          >
            Skip to email-only
          </button>
        ) : null}
      </div>

      {done ? (
        <div className="id-result" role="status">
          <p className="liveness-ok">
            {done.label} verified for this session. PII fields are redacted in
            evidence until you reveal them.
          </p>
          <ul className="id-field-list">
            {Object.keys(done.fields).map((key) => (
              <li key={key}>
                <span>{key.replace(/_/g, " ")}</span>
                <em>REDACTED</em>
              </li>
            ))}
          </ul>
          {done.disclosures.map((line) => (
            <p className="id-disclosure" key={line}>
              {line}
            </p>
          ))}
        </div>
      ) : null}
      {error ? <p className="liveness-error">{error}</p> : null}
    </div>
  );
}
