/**
 * Landing stage.
 *
 * Structure borrows the parts of Apple's and Cluely's pages that actually do
 * work rather than the parts that are just fashion: an oversized headline with
 * tight tracking, one clear primary action, a live product visual instead of a
 * screenshot, and generous vertical rhythm so each idea lands alone.
 *
 * The globe is the hero because it states the premise without a sentence: a
 * search engine sweeping for you, surfacing fragments of your footprint, each
 * one vanishing again. The vanishing is load-bearing — it is the retention
 * promise, animated.
 *
 * Ordering rule kept from the first version: the refusals appear *before* the
 * camera is ever mentioned. Someone about to grant face access should already
 * know we cannot scan a third party and that nothing is kept.
 */

import {Suspense, lazy, type ReactNode} from "react";

import {BrandIcon, type BrandKey} from "./BrandIcon";

/**
 * Lazy, matching how App.tsx already defers Scene3D and MirrorMap.
 *
 * Importing the globe eagerly pulled three.js and react-three-fiber into the
 * entry chunk — 235KB became 1,208KB, so the headline waited on the renderer
 * before it could paint. Deferring it keeps first paint immediate and lets the
 * globe fade in a beat later, which is also the nicer entrance.
 */
const SearchGlobe = lazy(() =>
  import("./SearchGlobe").then((module) => ({default: module.SearchGlobe})),
);

type Props = {
  onBegin: () => void;
  onMockPreview: () => void;
  busy?: boolean;
  serviceReady?: boolean;
};

const PLATFORMS: {brand: BrandKey; name: string}[] = [
  {brand: "linkedin", name: "LinkedIn"},
  {brand: "instagram", name: "Instagram"},
  {brand: "github", name: "GitHub"},
  {brand: "reddit", name: "Reddit"},
  {brand: "x", name: "X"},
  {brand: "strava", name: "Strava"},
  {brand: "facebook", name: "Facebook"},
  {brand: "pinterest", name: "Pinterest"},
  {brand: "twitch", name: "Twitch"},
  {brand: "steam", name: "Steam"},
  {brand: "email", name: "Breach corpora"},
  {brand: "records", name: "Public records"},
];

function Trust({label, children}: {label: string; children: ReactNode}) {
  return (
    <div>
      <strong>{label}</strong>
      <span>{children}</span>
    </div>
  );
}

export function MirrorLanding({onBegin, onMockPreview, busy, serviceReady = true}: Props) {
  return (
    <div className="stage stage--landing" data-stage="landing">
      <div className="landing-v2">
        {/* ── hero ── */}
        <section className="hero">
          <div className="hero-copy">
            <div className="landing-mark">
              <i aria-hidden="true">M</i>
              <span>DDU / Mirror</span>
            </div>

            <h1>
              See what
              <br />
              they&apos;d see.
            </h1>

            <p className="tagline">Start with yourself.</p>

            <p className="lede">
              The same intelligence engine an attacker would point at you, aimed
              inward instead. Prove you&apos;re you, choose what to look for, and
              watch your exposure assemble itself &mdash; then take it apart.
            </p>

            <div className="landing-cta">
              <button
                className="btn-primary btn-lg"
                disabled={busy || !serviceReady}
                onClick={onBegin}
                type="button"
              >
                {serviceReady ? "Verify and begin" : "Waiting for the intelligence service…"}
              </button>
              <button className="btn-quiet btn-lg" disabled={busy} onClick={onMockPreview} type="button">
                See a sample scan
              </button>
            </div>

            <p className="hero-fineprint">
              No third-party scanning. Nothing stored. Destroyed when you leave.
            </p>
          </div>

          <div className="hero-visual">
            {/* Placeholder keeps the hero's height stable so the copy doesn't
                jump when the globe chunk arrives. */}
            <Suspense
              fallback={
                <div className="globe-stage">
                  <div className="globe-halo" aria-hidden="true" />
                  <div className="globe-fallback" aria-hidden="true" />
                </div>
              }
            >
              <SearchGlobe />
            </Suspense>
          </div>
        </section>

        {/* ── surface strip ── */}
        <section className="strip">
          <p className="strip-label">Looks across</p>
          {/* Doubled so the -50% marquee translate loops seamlessly. */}
          <div className="strip-track">
            {[...PLATFORMS, ...PLATFORMS].map((item, index) => (
              <span key={`${item.brand}-${index}`}>
                <BrandIcon brand={item.brand} colored size={19} />
                {item.name}
              </span>
            ))}
          </div>
        </section>

        {/* ── how it works ── */}
        <section className="steps-band">
          <h2>Four steps. You approve every one.</h2>
          <div className="steps-row">
            <article>
              <span className="step-n">01</span>
              <h3>Prove it&apos;s you</h3>
              <p>
                A live face challenge, processed in your browser. An emailed code
                only proves someone had your inbox.
              </p>
            </article>
            <article>
              <span className="step-n">02</span>
              <h3>Choose the scope</h3>
              <p>
                Say what to look for. Every step shows whether it contacts anyone
                outside this machine.
              </p>
            </article>
            <article>
              <span className="step-n">03</span>
              <h3>Approve each move</h3>
              <p>
                The agent drafts; it never acts. Approve, edit, or reject &mdash; and
                the graph grows only as you allow.
              </p>
            </article>
            <article>
              <span className="step-n">04</span>
              <h3>Take it apart</h3>
              <p>
                Reject what isn&apos;t you and watch paths break. Mark things fixed &mdash;
                the permanent ones refuse.
              </p>
            </article>
          </div>
        </section>

        {/* ── trust ── */}
        <section className="trust-band">
          <div className="landing-trust">
            <Trust label="Only you">
              There is no field to type someone else&apos;s name into. Every scan is
              asserted against an identity you proved you control.
            </Trust>
            <Trust label="Live proof">
              A face challenge shows a person is present now. A password only shows
              someone once had one.
            </Trust>
            <Trust label="Nothing kept">
              Findings live in memory for the session. Your face frame is matched,
              then destroyed &mdash; never stored.
            </Trust>
            <Trust label="You decide">
              The agent proposes; it never acts. Approve, edit, or reject every
              step, and reject any finding that isn&apos;t you.
            </Trust>
          </div>

          <div className="landing-foot">
            <button
              className="btn-primary btn-lg"
              disabled={busy || !serviceReady}
              onClick={onBegin}
              type="button"
            >
              Verify and begin
            </button>
            <p>Takes about a minute. You can end and wipe everything at any point.</p>
          </div>
        </section>
      </div>
    </div>
  );
}
