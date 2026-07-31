/**
 * Scope stage — what should the agent look for?
 *
 * This is the Track 3 approve/edit/reject decision moved *earlier*, to
 * where it costs the user nothing. The graph view already lets you
 * approve or reject each proposal one at a time, which is the right
 * granularity mid-scan but the wrong one at the start: nobody wants to
 * be asked five separate questions before they have seen anything.
 *
 * So this screen is the batch form of the same decision. Every item you
 * leave on becomes a proposal the agent drafts; every item you turn off
 * is a step it will not propose at all. Nothing here executes — turning
 * something on is consent to *ask*, not consent to run, and each one
 * still lands as an individually approvable card.
 *
 * The two labels that matter are `external` and `local only`. A user
 * deciding what to allow should be able to see which steps talk to a
 * third party and which never leave our own process.
 */

import {useMemo, useState} from "react";

export type ScopeKey =
  | "discovery.accounts"
  | "discovery.breaches"
  | "intel.linkability"
  | "advisor.records"
  | "vision.photos";

export type ScopeChoice = {
  keys: ScopeKey[];
  state?: string;
  county?: string;
};

type Item = {
  key: ScopeKey;
  title: string;
  blurb: string;
  external: string | null;
  defaultOn: boolean;
};

const ITEMS: Item[] = [
  {
    key: "discovery.breaches",
    title: "Breach exposure",
    blurb:
      "Check your verified email against known breach corpora. This is where irreversible exposure shows up — data you cannot withdraw.",
    external: "Have I Been Pwned",
    defaultOn: true,
  },
  {
    key: "discovery.accounts",
    title: "Accounts under your handle",
    blurb:
      "Look for profiles using your handle across a curated set of high-signal platforms. Username matches are not proof, so you can reject any that aren't yours.",
    external: "Sherlock",
    defaultOn: true,
  },
  {
    key: "intel.linkability",
    title: "Are your accounts linkable?",
    blurb:
      "Compare the accounts you approved for shared avatars, copied bio phrasing, cross-links, and handle similarity — whether a pseudonymous account is provably you.",
    external: null,
    defaultOn: true,
  },
  {
    key: "advisor.records",
    title: "Public records where you live",
    blurb:
      "Which classes of record are public by statute in your state, what each one discloses, and the documented suppression path. No lookup is performed and no record is retrieved.",
    external: null,
    defaultOn: true,
  },
  {
    key: "vision.photos",
    title: "Photo intelligence",
    blurb:
      "Read EXIF, detect exposed objects like plates and badges, and infer location from image content. Runs on photos you choose to upload.",
    external: null,
    defaultOn: false,
  },
];

const STATES = [
  ["", "Select your state"],
  ["TX", "Texas"],
  ["WA", "Washington"],
  ["CA", "California"],
  ["IL", "Illinois"],
  ["FL", "Florida"],
  ["NY", "New York"],
];

type Props = {
  onConfirm: (choice: ScopeChoice) => void;
  onBack?: () => void;
  assurance?: "live_face" | "id_document" | "email_only";
  busy?: boolean;
};

function assuranceLabel(assurance: Props["assurance"]) {
  if (assurance === "live_face") return "Live face verified";
  if (assurance === "id_document") return "ID verified";
  return "Email-only assurance";
}

function assuranceClass(assurance: Props["assurance"]) {
  if (assurance === "live_face") return "is-live";
  if (assurance === "id_document") return "is-id";
  return "is-email";
}

export function ScanScope({onConfirm, onBack, assurance = "email_only", busy}: Props) {
  const [on, setOn] = useState<Set<ScopeKey>>(
    () => new Set(ITEMS.filter((i) => i.defaultOn).map((i) => i.key)),
  );
  const [state, setState] = useState("");
  const [county, setCounty] = useState("");

  const needsState = on.has("advisor.records");
  const chosen = useMemo(() => ITEMS.filter((i) => on.has(i.key)), [on]);
  const externals = chosen.filter((i) => i.external).map((i) => i.external);

  function toggle(key: ScopeKey) {
    setOn((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const blocked = needsState && !state;

  return (
    <div className="stage" data-stage="scope">
      <div className="stage-inner">
        <div className="stage-steps" aria-label="Progress">
          <span className="is-done">
            <b>1</b> Identity
          </span>
          <i aria-hidden="true" />
          <span className="is-done">
            <b>2</b> Live check
          </span>
          <i aria-hidden="true" />
          <span className="is-current">
            <b>3</b> Scope
          </span>
          <i aria-hidden="true" />
          <span>
            <b>4</b> Scan
          </span>
        </div>

        <div className="stage-card">
          <div className="stage-head">
            <p className="eyebrow">Step 3 of 4</p>
            <h2>What should it look for?</h2>
            <p>
              Turn on what you want examined. Each one becomes a proposal you can
              still approve, edit, or reject individually before it runs &mdash;
              nothing here starts a scan by itself.
            </p>
            <p style={{marginTop: 10}}>
              <span className={`assurance ${assuranceClass(assurance)}`}>
                {assuranceLabel(assurance)}
              </span>
            </p>
          </div>

          <div className="scope-bulk">
            <button onClick={() => setOn(new Set(ITEMS.map((i) => i.key)))} type="button">
              Look for everything
            </button>
            <button
              onClick={() => setOn(new Set(ITEMS.filter((i) => i.defaultOn).map((i) => i.key)))}
              type="button"
            >
              Recommended only
            </button>
            <button onClick={() => setOn(new Set())} type="button">
              Clear all
            </button>
          </div>

          <div className="scope-grid">
            {ITEMS.map((item) => {
              const active = on.has(item.key);
              return (
                <label className={`scope-item ${active ? "is-on" : ""}`} key={item.key}>
                  <input checked={active} onChange={() => toggle(item.key)} type="checkbox" />
                  <div>
                    <h4>{item.title}</h4>
                    <p>{item.blurb}</p>
                    <div className="scope-meta">
                      {item.external ? (
                        <em className="is-external">Contacts {item.external}</em>
                      ) : (
                        <em className="is-local">Local only</em>
                      )}
                    </div>
                  </div>
                </label>
              );
            })}
          </div>

          {needsState ? (
            <div style={{marginTop: 16, display: "flex", gap: 10, flexWrap: "wrap"}}>
              <label style={{flex: "1 1 200px"}}>
                <span className="panel-label" style={{display: "block", marginBottom: 6}}>
                  Your state
                </span>
                <select onChange={(e) => setState(e.target.value)} value={state}>
                  {STATES.map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{flex: "1 1 200px"}}>
                <span className="panel-label" style={{display: "block", marginBottom: 6}}>
                  County (optional)
                </span>
                <input
                  onChange={(e) => setCounty(e.target.value)}
                  placeholder="e.g. Dallas"
                  value={county}
                />
              </label>
            </div>
          ) : null}

          <div className="stage-foot">
            <p className="note">
              {chosen.length === 0
                ? "Nothing selected — the agent will have nothing to propose."
                : externals.length > 0
                  ? `${chosen.length} selected. Outbound contact: ${[...new Set(externals)].join(", ")}.`
                  : `${chosen.length} selected. Nothing leaves this machine.`}
            </p>
            <div style={{display: "flex", gap: 10}}>
              {onBack ? (
                <button className="btn-quiet" onClick={onBack} type="button">
                  Back
                </button>
              ) : null}
              <button
                className="btn-primary"
                disabled={busy || chosen.length === 0 || blocked}
                onClick={() => onConfirm({keys: [...on], state, county})}
                type="button"
              >
                {blocked ? "Choose your state" : `Draft ${chosen.length} proposal${chosen.length === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
