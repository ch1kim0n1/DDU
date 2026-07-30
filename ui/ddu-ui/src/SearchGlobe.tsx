/**
 * Landing hero — Earth, sweeping, with discoveries surfacing around it.
 *
 * The globe is a real map: dots are placed only where Natural Earth says there
 * is land (see globe-land.ts), so the continents are recognisable as they
 * rotate rather than being an abstract dot cloud. Ocean gets a sparse, dim
 * scatter so the sphere still reads as a sphere at the limb.
 *
 * The metaphor is the product: a search engine sweeping for you, surfacing
 * fragments of your public footprint, each one fading out again. The fading is
 * load-bearing — it is the retention promise, animated. A card that appeared
 * and stayed would contradict the copy beside it.
 *
 * The globe is 3D; the surfacing cards are HTML above it. Glass, blur and real
 * type are cheaper and better looking in the DOM than as textured planes, and
 * it keeps the platform names available to screen readers instead of baked into
 * a canvas.
 */

import {Canvas, useFrame} from "@react-three/fiber";
import {useEffect, useMemo, useRef, useState} from "react";
import * as THREE from "three";

import {BrandIcon, type BrandKey} from "./BrandIcon";
import {samplePoints} from "./globe-land";

const RADIUS = 1.55;
/** Total sphere samples before the land/ocean split. */
const SAMPLES = 14000;

/* ── globe ───────────────────────────────────────────────────────────── */

function Earth() {
  const group = useRef<THREE.Group>(null);
  // Sampling walks 14k points against a bitmap; do it once, not per frame.
  const {land, ocean} = useMemo(() => samplePoints(SAMPLES, RADIUS), []);

  useFrame((_, delta) => {
    if (group.current) group.current.rotation.y += delta * 0.155;
  });

  return (
    <group ref={group}>
      {/* Ocean: dim and small, so the limb of the sphere is still described. */}
      <points>
        <bufferGeometry>
          <bufferAttribute args={[ocean, 3]} attach="attributes-position" />
        </bufferGeometry>
        <pointsMaterial
          color="#1d5f78"
          depthWrite={false}
          opacity={0.34}
          size={0.0125}
          sizeAttenuation
          transparent
        />
      </points>

      {/* Land: brighter and larger — this is what makes it read as a map. */}
      <points>
        <bufferGeometry>
          <bufferAttribute args={[land, 3]} attach="attributes-position" />
        </bufferGeometry>
        <pointsMaterial
          color="#7ce7ff"
          depthWrite={false}
          opacity={0.95}
          size={0.027}
          sizeAttenuation
          transparent
        />
      </points>
    </group>
  );
}

/**
 * Interior shell that hides the far side of the globe.
 *
 * Must be genuinely opaque (`transparent={false}`). With `transparent` set it
 * joins the transparent render pass alongside the point clouds, where ordering
 * is by object distance rather than per-fragment depth — the core then painted
 * over the near-side land dots and left only a rim of points at the limb,
 * which looked exactly like the continents had failed to generate. Opaque, it
 * renders in the first pass and the points depth-test against it correctly:
 * near side draws, far side is culled.
 */
function Core() {
  return (
    <mesh>
      <sphereGeometry args={[RADIUS * 0.972, 48, 36]} />
      <meshBasicMaterial color="#04121d" transparent={false} />
    </mesh>
  );
}

/** Atmosphere: back-facing shell tinted at the rim. */
function Atmosphere() {
  return (
    <mesh scale={1.055}>
      <sphereGeometry args={[RADIUS, 48, 36]} />
      <meshBasicMaterial
        color="#2f9dc4"
        opacity={0.11}
        side={THREE.BackSide}
        transparent
      />
    </mesh>
  );
}

/**
 * A sweeping ring flush against the sphere.
 *
 * `axis` picks which way it travels: "y" is the original horizontal band
 * rising and falling, "x" sweeps in from the sides. Two crossing sweeps read as
 * a search working the whole surface rather than one band pacing up and down.
 *
 * The ring always spans the sphere's *cross-section* at its current offset, not
 * the full radius — otherwise it detaches from the surface and floats as a hoop
 * around the globe near the poles.
 */
function ScanRing({
  axis,
  speed,
  phase = 0,
  color = "#a8f0ff",
}: {
  axis: "x" | "y";
  speed: number;
  phase?: number;
  color?: string;
}) {
  const ring = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!ring.current) return;
    const t = state.clock.elapsedTime * speed + phase;
    const offset = Math.sin(t) * RADIUS * 0.94;
    const chord = Math.sqrt(Math.max(0.02, RADIUS * RADIUS - offset * offset));

    if (axis === "y") ring.current.position.set(0, offset, 0);
    else ring.current.position.set(offset, 0, 0);

    ring.current.scale.setScalar(chord / RADIUS);
    (ring.current.material as THREE.Material).opacity = 0.26 + Math.cos(t) * 0.15;
  });

  // A torus lies in its own XY plane, so the horizontal band needs tipping onto
  // the XZ plane and the side sweep needs standing upright about Y.
  const rotation: [number, number, number] =
    axis === "y" ? [Math.PI / 2, 0, 0] : [0, Math.PI / 2, 0];

  return (
    <mesh ref={ring} rotation={rotation}>
      <torusGeometry args={[RADIUS, 0.005, 8, 96]} />
      <meshBasicMaterial color={color} transparent />
    </mesh>
  );
}

function Scene() {
  return (
    <>
      <ambientLight intensity={0.65} />
      <Core />
      <Earth />
      <Atmosphere />
      {/* Two crossing sweeps: one rising and falling, one coming in from the
          sides. Speeds are deliberately not multiples of each other so the
          crossing point drifts instead of settling into a repeating figure. */}
      <ScanRing axis="y" speed={0.4} />
      <ScanRing axis="x" speed={0.29} phase={1.1} color="#7ce7ff" />
    </>
  );
}

/* ── surfacing cards ─────────────────────────────────────────────────── */

type Discovery = {
  id: string;
  platform: string;
  label: string;
  x: number;
  y: number;
  brand: BrandKey;
};

const DISCOVERIES: Discovery[] = [
  {id: "d1", platform: "LinkedIn", label: "Employer + location public", x: 2, y: 15, brand: "linkedin"},
  {id: "d2", platform: "Instagram", label: "GPS in 3 photos", x: 97, y: 10, brand: "instagram"},
  {id: "d3", platform: "GitHub", label: "Commit email exposed", x: 0, y: 59, brand: "github"},
  {id: "d4", platform: "Breach corpus", label: "2019 dump · irreversible", x: 99, y: 67, brand: "email"},
  {id: "d5", platform: "Reddit", label: "Handle reused", x: 96, y: 38, brand: "reddit"},
  {id: "d6", platform: "X", label: "Discoverable by phone", x: 4, y: 37, brand: "x"},
  {id: "d7", platform: "Strava", label: "Route starts at home", x: 13, y: 82, brand: "strava"},
  {id: "d8", platform: "Public records", label: "Deed names your address", x: 92, y: 87, brand: "records"},
];

function useSurfacing(total: number, visible = 3, intervalMs = 1900) {
  const [cursor, setCursor] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    // Guarded: matchMedia is absent under jsdom and server rendering, and an
    // unguarded call takes the app down rather than losing a preference.
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
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

  // Reduced motion shows everything statically rather than nothing, so the page
  // still says what the globe is doing.
  if (reduced) return new Set(Array.from({length: total}, (_, i) => i));

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
    <div className="globe-stage">
      <div className="globe-halo" aria-hidden="true" />

      {webgl ? (
        <Canvas
          camera={{position: [0, 0.35, 4.35], fov: 42}}
          dpr={[1, 2]}
          gl={{alpha: true, antialias: true, powerPreference: "low-power"}}
        >
          <Scene />
        </Canvas>
      ) : (
        <div className="globe-fallback" aria-hidden="true" />
      )}

      <div className="globe-finds">
        {DISCOVERIES.map((item, index) => (
          <div
            className={`find-card ${active.has(index) ? "is-in" : ""}`}
            key={item.id}
            // Cards past the midpoint anchor by their RIGHT edge — a card's
            // width depends on its label, so no single `left` fits them all and
            // the right-hand ones clipped out of the stage.
            style={
              item.x >= 50
                ? {right: `${100 - item.x}%`, top: `${item.y}%`}
                : {left: `${item.x}%`, top: `${item.y}%`}
            }
          >
            <span className="find-icon">
              <BrandIcon brand={item.brand} colored size={15} />
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
