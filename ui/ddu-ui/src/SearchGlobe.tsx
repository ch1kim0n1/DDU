/**
 * Landing hero — a rotating globe with discoveries surfacing around it.
 *
 * The metaphor is deliberate: this is what a search engine pointed at *you*
 * looks like. The globe sweeps, fragments of your public footprint surface
 * around it, and each one fades out again — because the product's promise is
 * that nothing is retained. A card that appeared and stayed would be telling
 * the opposite story from the copy next to it.
 *
 * Built on react-three-fiber (already a dependency for the exposure graph)
 * rather than a canvas or GIF, so it shares the renderer the rest of the app
 * already ships and stays crisp at any density.
 *
 * The globe is 3D; the surfacing cards are HTML positioned over it. That split
 * is intentional — glass, blur and real type are far cheaper and better looking
 * in DOM than as textured planes in the scene, and it keeps the icons
 * accessible to screen readers instead of baking them into a canvas.
 */

import {Canvas, useFrame} from "@react-three/fiber";
import {useEffect, useMemo, useRef, useState} from "react";
import * as THREE from "three";

/* ── geometry ─────────────────────────────────────────────────────────── */

/** Even point distribution over a sphere. Latitude rings clump at the poles. */
function fibonacciSphere(count: number, radius: number): Float32Array {
  const out = new Float32Array(count * 3);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    out[i * 3] = Math.cos(theta) * r * radius;
    out[i * 3 + 1] = y * radius;
    out[i * 3 + 2] = Math.sin(theta) * r * radius;
  }
  return out;
}

function GlobeDots({radius}: {radius: number}) {
  const points = useRef<THREE.Points>(null);
  const positions = useMemo(() => fibonacciSphere(1400, radius), [radius]);

  useFrame((_, delta) => {
    if (points.current) points.current.rotation.y += delta * 0.075;
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute args={[positions, 3]} attach="attributes-position" />
      </bufferGeometry>
      <pointsMaterial
        color="#4fd6ff"
        depthWrite={false}
        opacity={0.85}
        size={0.021}
        sizeAttenuation
        transparent
      />
    </points>
  );
}

function GlobeWire({radius}: {radius: number}) {
  const mesh = useRef<THREE.Mesh>(null);
  useFrame((_, delta) => {
    if (mesh.current) mesh.current.rotation.y += delta * 0.045;
  });
  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[radius * 0.985, 26, 20]} />
      <meshBasicMaterial color="#1d7f9e" opacity={0.16} transparent wireframe />
    </mesh>
  );
}

/** Soft inner body so dots on the far side read as behind something. */
function GlobeCore({radius}: {radius: number}) {
  return (
    <mesh>
      <sphereGeometry args={[radius * 0.955, 48, 36]} />
      <meshBasicMaterial color="#05141c" opacity={0.92} transparent />
    </mesh>
  );
}

/** The sweep. Rises and falls so it reads as scanning, not spinning. */
function ScanRing({radius}: {radius: number}) {
  const ring = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!ring.current) return;
    const t = state.clock.elapsedTime * 0.42;
    const y = Math.sin(t) * radius * 0.92;
    ring.current.position.y = y;
    // Keep the ring flush with the sphere's cross-section at this height.
    const chord = Math.sqrt(Math.max(0.02, radius * radius - y * y));
    ring.current.scale.setScalar(chord / radius);
    const material = ring.current.material as THREE.Material;
    material.opacity = 0.34 + Math.cos(t) * 0.14;
  });

  return (
    <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[radius, 0.006, 8, 96]} />
      <meshBasicMaterial color="#7ce7ff" transparent />
    </mesh>
  );
}

function Scene() {
  const radius = 1.55;
  return (
    <>
      <ambientLight intensity={0.6} />
      <GlobeCore radius={radius} />
      <GlobeWire radius={radius} />
      <GlobeDots radius={radius} />
      <ScanRing radius={radius} />
    </>
  );
}

/* ── surfacing cards ─────────────────────────────────────────────────── */

type Discovery = {
  id: string;
  platform: string;
  label: string;
  /** Percentage position around the globe. */
  x: number;
  y: number;
  icon: "linkedin" | "instagram" | "github" | "x" | "reddit" | "photo" | "mail" | "pin";
};

const DISCOVERIES: Discovery[] = [
  {id: "d1", platform: "LinkedIn", label: "Employer + location public", x: 2, y: 16, icon: "linkedin"},
  {id: "d2", platform: "Instagram", label: "GPS in 3 photos", x: 97, y: 11, icon: "instagram"},
  {id: "d3", platform: "GitHub", label: "Commit email exposed", x: 0, y: 60, icon: "github"},
  {id: "d4", platform: "Breach corpus", label: "2019 dump · irreversible", x: 99, y: 68, icon: "mail"},
  {id: "d5", platform: "Reddit", label: "Handle reused", x: 96, y: 39, icon: "reddit"},
  {id: "d6", platform: "X", label: "Discoverable by phone", x: 4, y: 38, icon: "x"},
  {id: "d7", platform: "Photo", label: "Licence plate legible", x: 14, y: 83, icon: "photo"},
  {id: "d8", platform: "Public records", label: "Deed names your address", x: 92, y: 88, icon: "pin"},
];

/** Simple monochrome glyphs — recognisable without replicating brand marks. */
function Glyph({name}: {name: Discovery["icon"]}) {
  const common = {fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const};
  switch (name) {
    case "linkedin":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect height="16" rx="2" width="16" x="4" y="4" {...common} />
          <path d="M8 11v6M8 8v.01M12 17v-3.5a2 2 0 0 1 4 0V17" {...common} />
        </svg>
      );
    case "instagram":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect height="16" rx="4.5" width="16" x="4" y="4" {...common} />
          <circle cx="12" cy="12" r="3.4" {...common} />
          <path d="M17 7.5v.01" {...common} />
        </svg>
      );
    case "github":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M15 21v-3a3 3 0 0 0-.7-2c2.3-.3 4-1.5 4-5a4 4 0 0 0-1-2.7 3.6 3.6 0 0 0-.1-2.7s-1 0-2.4 1.4a8.5 8.5 0 0 0-4.6 0C8.8 5 7.8 5 7.8 5a3.6 3.6 0 0 0-.1 2.7A4 4 0 0 0 6.7 10c0 3.5 1.7 4.7 4 5a3 3 0 0 0-.7 2v3"
            {...common}
          />
          <path d="M10 20c-2.5.8-4-.4-5-2" {...common} />
        </svg>
      );
    case "x":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 5l14 14M19 5L5 19" {...common} />
        </svg>
      );
    case "reddit":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="13" r="7" {...common} />
          <path d="M15 5.5l-1.6 3.6M9.6 13v.01M14.4 13v.01M9.6 16c1.4 1 3.4 1 4.8 0" {...common} />
          <circle cx="15.4" cy="4.6" r="1.3" {...common} />
        </svg>
      );
    case "photo":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect height="14" rx="2.5" width="18" x="3" y="5" {...common} />
          <circle cx="8.5" cy="10" r="1.6" {...common} />
          <path d="M4 17l5-4.5 4 3.5 3-2.5 4 3.5" {...common} />
        </svg>
      );
    case "mail":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect height="13" rx="2.5" width="18" x="3" y="6" {...common} />
          <path d="M3.5 8l8.5 6 8.5-6" {...common} />
        </svg>
      );
    case "pin":
    default:
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 21s6-5.3 6-10a6 6 0 1 0-12 0c0 4.7 6 10 6 10z" {...common} />
          <circle cx="12" cy="11" r="2.3" {...common} />
        </svg>
      );
  }
}

/**
 * Cycles which discoveries are on screen. Two visible at a time, each for a
 * beat, then gone — the appearing *and* disappearing is the point.
 */
function useSurfacing(total: number, visible = 3, intervalMs = 1900) {
  const [cursor, setCursor] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    // Guarded: matchMedia is absent in jsdom and in server rendering, and an
    // unguarded call takes the whole app down rather than just losing a
    // motion preference.
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
    // Safari below 14 only has the deprecated addListener form.
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    }
    query.addListener(onChange);
    return () => query.removeListener(onChange);
  }, []);

  useEffect(() => {
    if (reduced) return;
    const timer = window.setInterval(() => setCursor((c) => c + visible), intervalMs);
    return () => window.clearInterval(timer);
  }, [reduced, visible, intervalMs]);

  // Reduced motion: show a static, non-animating set instead of nothing, so the
  // page still communicates what the globe is doing.
  if (reduced) return new Set([0, 1, 2, 3, 4, 5, 6, 7].slice(0, total));

  const active = new Set<number>();
  for (let i = 0; i < visible; i += 1) active.add((cursor + i) % total);
  return active;
}

/* ── public component ────────────────────────────────────────────────── */

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function SearchGlobe() {
  const [webgl] = useState(supportsWebGL);
  const active = useSurfacing(DISCOVERIES.length);

  return (
    <div className="globe-stage" aria-hidden="true">
      <div className="globe-halo" />

      {webgl ? (
        <Canvas
          camera={{position: [0, 0, 4.4], fov: 42}}
          dpr={[1, 2]}
          gl={{alpha: true, antialias: true, powerPreference: "low-power"}}
        >
          <Scene />
        </Canvas>
      ) : (
        // No WebGL: a CSS orb still carries the idea rather than leaving a hole.
        <div className="globe-fallback" />
      )}

      <div className="globe-finds">
        {DISCOVERIES.map((item, index) => (
          <div
            className={`find-card ${active.has(index) ? "is-in" : ""}`}
            key={item.id}
            // Cards past the midpoint anchor to their RIGHT edge. Anchoring
            // everything by `left` pushed the right-hand cards past the stage
            // bounds and clipped them, and a card's width depends on its label
            // so there is no single left value that fits them all.
            style={
              item.x >= 50
                ? {right: `${100 - item.x}%`, top: `${item.y}%`}
                : {left: `${item.x}%`, top: `${item.y}%`}
            }
          >
            <span className="find-icon">
              <Glyph name={item.icon} />
            </span>
            <span className="find-text">
              <b>{item.platform}</b>
              <em>{item.label}</em>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
