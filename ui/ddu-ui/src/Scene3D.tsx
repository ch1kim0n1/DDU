/**
 * The exposure graph, as a data encoding rather than a decorative scene.
 *
 * Every visual channel carries a value. Nothing here is chosen because it
 * looks nice in isolation:
 *
 *   distance from centre  →  hop_depth   "how far they got from one clue"
 *   height                →  severity    a taller spire is a worse finding
 *   colour                →  reversible  cyan you can undo, amber you cannot
 *   cap brightness/size   →  confidence  a guess glows dimmer than a fact
 *   links                 →  parent_id   lit when the chain is a live path
 *
 * The previous version spent colour on `verification_state` and laid nodes out
 * along a receding Z axis over a square grid. That put the palette's loudest
 * channel on a secondary attribute and made the scene read as coloured blocks
 * on graph paper. Reversibility is the product's actual argument — the whole
 * point is which parts of your exposure you can still take back — so it earns
 * colour, and the layout is now concentric because "distance from you" is the
 * thing the narrative keeps describing.
 *
 * The centre is you. Rings are hops. That reads without a caption, which is
 * the test a visualisation has to pass.
 */

import {Html, Line, OrbitControls} from "@react-three/drei";
import {Canvas, useFrame} from "@react-three/fiber";
import {memo, useEffect, useMemo, useRef, useState} from "react";
import * as THREE from "three";

import {ErrorBoundary} from "./ErrorBoundary";
import type {AttackPath, Finding} from "./mirror-types";

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      canvas.getContext("webgl2") ||
        canvas.getContext("webgl") ||
        canvas.getContext("experimental-webgl"),
    );
  } catch {
    return false;
  }
}

function SceneFallback({findings}: {findings: Finding[]}) {
  const sorted = [...findings].sort((a, b) => b.severity_score - a.severity_score);
  return (
    <div className="scene-fallback" aria-label="2D exposure list fallback">
      <strong>3D view unavailable</strong>
      <p>WebGL is not available in this browser. Showing a text hierarchy instead.</p>
      <ul>
        {sorted.map((finding) => (
          <li className={`severity-${finding.severity}`} key={finding.id}>
            <span className="hop">H{finding.hop_depth}</span>
            <span className={`state-chip state-${finding.verification_state}`}>
              {finding.verification_state}
            </span>
            <strong>{finding.label}</strong>
            <small>{finding.detail}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── palette ──────────────────────────────────────────────────────────
   Drawn from the same tokens as the rest of the interface (--v2-accent
   and friends) so the scene belongs to the product rather than to
   three.js's default look. */

const C_SEED = "#7ce7ff";
const C_REVERSIBLE = "#4fd6ff";
const C_IRREVERSIBLE = "#ec9a3c";
/** Irreversible *and* severe — the findings the whole product is about. */
const C_PERMANENT_BAD = "#ff7a59";
const C_REMEDIATED = "#39414f";

function nodeColor(finding: Finding, remediated: boolean): string {
  if (remediated) return C_REMEDIATED;
  if (!finding.reversible) {
    return finding.severity_score > 0.6 ? C_PERMANENT_BAD : C_IRREVERSIBLE;
  }
  return C_REVERSIBLE;
}

interface LayoutNode {
  finding: Finding;
  position: [number, number, number];
}

interface Scene3DProps {
  findings: Finding[];
  attackPaths: AttackPath[];
  selectedId?: string | null;
  remediatedIds?: Set<string>;
  refusedIds?: Set<string>;
  hiddenIds?: Set<string>;
  onSelect: (finding: Finding) => void;
}

/** Radius of a hop ring. Hop 0 is you, at the origin. */
function hopRadius(hop: number): number {
  return hop === 0 ? 0 : 2.6 + (hop - 1) * 2.5;
}

/**
 * Concentric layout: each hop is a ring, members spread evenly around it.
 *
 * Children are nudged toward their parent's angle so a chain reads as a
 * spoke running outward rather than as an arbitrary chord across the disc —
 * the edges then trace the actual pivot the narrative describes.
 */
function layoutFindings(findings: Finding[]): LayoutNode[] {
  const byHop = new Map<number, Finding[]>();
  findings.forEach((finding) => {
    const bucket = byHop.get(finding.hop_depth) || [];
    bucket.push(finding);
    byHop.set(finding.hop_depth, bucket);
  });

  const angleOf = new Map<string, number>();
  const output: LayoutNode[] = [];

  for (const hop of [...byHop.keys()].sort((a, b) => a - b)) {
    const radius = hopRadius(hop);
    // Order by the parent's angle, then spread the whole ring evenly in that
    // order. Families stay adjacent *and* the full circle gets used.
    //
    // Blending each child's angle toward its parent instead — the obvious
    // approach — collapses the layout: every hop-1 finding shares one parent
    // (the seed), so they all landed inside a ~79° arc and three quarters of
    // every ring sat empty.
    const bucket = byHop.get(hop)!.sort((a, b) => {
      const pa = a.parent_id ? (angleOf.get(a.parent_id) ?? 0) : 0;
      const pb = b.parent_id ? (angleOf.get(b.parent_id) ?? 0) : 0;
      if (pa !== pb) return pa - pb;
      return b.severity_score - a.severity_score;
    });

    bucket.forEach((finding, index) => {
      // The per-hop offset stops rings lining up into visible spokes.
      const angle = (index / Math.max(1, bucket.length)) * Math.PI * 2 + hop * 0.4;
      angleOf.set(finding.id, angle);
      output.push({
        finding,
        position: [Math.cos(angle) * radius, 0, Math.sin(angle) * radius],
      });
    });
  }

  // Relaxation, so dense rings don't overlap their neighbours' spires.
  const minDist = 1.25;
  for (let iter = 0; iter < 14; iter += 1) {
    for (let i = 0; i < output.length; i += 1) {
      for (let j = i + 1; j < output.length; j += 1) {
        const a = output[i].position;
        const b = output[j].position;
        // The seed owns the origin; never push it off centre.
        if (output[i].finding.hop_depth === 0 || output[j].finding.hop_depth === 0) continue;
        const dx = b[0] - a[0];
        const dz = b[2] - a[2];
        const dist = Math.hypot(dx, dz) || 0.001;
        if (dist >= minDist) continue;
        const push = ((minDist - dist) / 2) * 0.6;
        const nx = dx / dist;
        const nz = dz / dist;
        output[i].position = [a[0] - nx * push, a[1], a[2] - nz * push];
        output[j].position = [b[0] + nx * push, b[1], b[2] + nz * push];
      }
    }
  }
  return output;
}

/* ── ground ───────────────────────────────────────────────────────────── */

/**
 * Hop rings on the floor, labelled.
 *
 * Replaces the square grid. A grid is generic 3D-scene furniture; these rings
 * are the axis of the chart — they say what "further out" costs you.
 */
function HopRings({maxHop}: {maxHop: number}) {
  const rings = [];
  for (let hop = 1; hop <= Math.max(1, maxHop); hop += 1) {
    const r = hopRadius(hop);
    rings.push(
      <group key={hop}>
        <mesh position={[0, -0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[r - 0.012, r + 0.012, 128]} />
          <meshBasicMaterial
            color={C_REVERSIBLE}
            opacity={0.16}
            side={THREE.DoubleSide}
            transparent
          />
        </mesh>
        <Html center position={[r, 0.06, 0]} zIndexRange={[8, 0]}>
          <span className="scene-tag">{hop === 1 ? "1 HOP" : `${hop} HOPS`}</span>
        </Html>
      </group>,
    );
  }
  return <>{rings}</>;
}

/** You. The thing everything else is measured from. */
function SeedMarker() {
  const halo = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (!halo.current) return;
    const t = state.clock.elapsedTime;
    halo.current.rotation.z = t * 0.35;
    const s = 1 + Math.sin(t * 1.6) * 0.06;
    halo.current.scale.set(s, s, s);
  });

  return (
    <group>
      <mesh position={[0, 0.62, 0]}>
        <octahedronGeometry args={[0.5, 0]} />
        <meshStandardMaterial
          color={C_SEED}
          emissive={C_SEED}
          emissiveIntensity={1.5}
          metalness={0.35}
          roughness={0.2}
        />
      </mesh>
      <mesh position={[0, 0.02, 0]} ref={halo} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.85, 0.95, 64]} />
        <meshBasicMaterial color={C_SEED} opacity={0.55} side={THREE.DoubleSide} transparent />
      </mesh>
      <Html center position={[0, 1.5, 0]} zIndexRange={[10, 0]}>
        <span className="scene-tag scene-tag--seed">YOU</span>
      </Html>
    </group>
  );
}

/* ── finding node ─────────────────────────────────────────────────────── */

function RiskNode({
  item,
  selected,
  remediated,
  refused,
  onSelect,
}: {
  item: LayoutNode;
  selected: boolean;
  remediated: boolean;
  refused: boolean;
  onSelect: () => void;
}) {
  const group = useRef<THREE.Group>(null);
  const spire = useRef<THREE.MeshStandardMaterial>(null);
  const [hovered, setHovered] = useState(false);

  const finding = item.finding;
  const severity = finding.severity_score;
  // Severity is the height. The floor is deliberately low so the difference
  // between a minor and a critical finding is a silhouette, not a subtlety.
  const height = 0.4 + severity * 3.4;
  const color = nodeColor(finding, remediated);
  // Confidence drives the cap: a hypothesis is visibly less solid than a fact.
  const confidence = Math.max(0.15, Math.min(1, finding.confidence));
  const capSize = 0.13 + confidence * 0.17;

  // Staggered materialisation by hop, so the graph assembles outward — the
  // same walk the attack-path narration describes, happening as you watch.
  const bornAt = useRef(0);
  const delay = Math.min(finding.hop_depth, 6) * 0.15;

  useEffect(() => {
    if (group.current) group.current.scale.setScalar(0.001);
    bornAt.current = 0;
  }, []);

  useFrame((state, delta) => {
    if (!group.current) return;
    if (bornAt.current === 0) bornAt.current = state.clock.elapsedTime;
    const age = state.clock.elapsedTime - bornAt.current - delay;

    if (age < 0) {
      group.current.scale.setScalar(0.001);
      return;
    }

    const target = remediated ? 0.82 : selected || hovered ? 1.14 : 1;
    const emerging = age < 0.55;
    const rate = emerging ? 1 - Math.pow(0.06, delta) : 1 - Math.pow(0.001, delta);
    group.current.scale.lerp(new THREE.Vector3(target, target, target), rate);

    if (refused) {
      // A refusal should feel like the system pushing back, not like decoration.
      group.current.rotation.y = Math.sin(state.clock.elapsedTime * 7) * 0.09;
    }
    if (spire.current) {
      spire.current.emissiveIntensity = remediated
        ? 0.02
        : 0.3 + severity * 1.1 + (selected ? 0.9 : 0) + (hovered ? 0.35 : 0);
    }
  });

  return (
    <group
      position={item.position}
      ref={group}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      onPointerEnter={(event) => {
        event.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerLeave={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
    >
      {/* Spire — tapered, so a row of them reads as a skyline of risk. */}
      <mesh castShadow position={[0, height / 2, 0]}>
        <cylinderGeometry args={[0.075, 0.2, height, 14]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.5}
          metalness={0.45}
          ref={spire}
          roughness={0.3}
        />
      </mesh>

      {/* Cap — size and glow are the confidence reading. */}
      <mesh position={[0, height + capSize * 0.6, 0]}>
        <sphereGeometry args={[capSize, 18, 18]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={remediated ? 0 : 0.7 + confidence * 0.8}
          roughness={0.18}
        />
      </mesh>

      {/* Base disc, so each spire is anchored to its ring rather than floating. */}
      <mesh position={[0, 0.005, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.3, 24]} />
        <meshBasicMaterial color={color} opacity={remediated ? 0.1 : 0.24} transparent />
      </mesh>

      {(selected || hovered) && (
        <Html center position={[0, height + 0.62, 0]} zIndexRange={[30, 0]}>
          <span className="scene-label">{finding.label}</span>
        </Html>
      )}

      {refused && (
        <Html center position={[0, 0.42, 0]} zIndexRange={[20, 0]}>
          <span className="scene-tag scene-tag--permanent">PERMANENT</span>
        </Html>
      )}
    </group>
  );
}

/* ── scene ────────────────────────────────────────────────────────────── */

function SceneContents({
  findings,
  attackPaths,
  selectedId,
  remediatedIds,
  refusedIds,
  onSelect,
}: Omit<Scene3DProps, "hiddenIds">) {
  const nodes = useMemo(() => layoutFindings(findings), [findings]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.finding.id, n])), [nodes]);
  const maxHop = useMemo(
    () => nodes.reduce((m, n) => Math.max(m, n.finding.hop_depth), 1),
    [nodes],
  );
  const activePathIds = useMemo(
    () => new Set(attackPaths.flatMap((path) => path.finding_ids)),
    [attackPaths],
  );

  const edges = useMemo(
    () =>
      nodes
        .filter((node) => node.finding.parent_id && byId.has(node.finding.parent_id))
        .map((node) => {
          const parent = byId.get(node.finding.parent_id!)!;
          const pathLit =
            activePathIds.has(node.finding.id) && activePathIds.has(parent.finding.id);
          return {node, parent, pathLit};
        }),
    [activePathIds, byId, nodes],
  );

  return (
    <>
      {/* Matches --v2-void, so the canvas and the panel around it are one surface. */}
      <color attach="background" args={["#06080c"]} />
      <fog attach="fog" args={["#06080c", 16, 42]} />
      <ambientLight intensity={0.55} />
      <directionalLight castShadow intensity={1.5} position={[6, 14, 6]} />
      {/* Cool key from below-left picks the spires out of the dark floor. */}
      <pointLight color={C_REVERSIBLE} intensity={28} position={[-8, 3, -6]} />
      <pointLight color={C_IRREVERSIBLE} intensity={14} position={[9, 2.5, 7]} />

      <HopRings maxHop={maxHop} />
      {/* Exactly one, always. It marks the origin, so it is drawn here rather
          than per-finding — the seed set can legitimately hold more than one
          hop-0 record, and rendering a marker for each stacked duplicate
          "YOU" labels on top of one another. */}
      <SeedMarker />

      {edges.map(({node, parent, pathLit}) => {
        // Arc the link over the floor rather than cutting through it, so a
        // chain is legible from the default camera instead of hiding inside
        // the spires it connects.
        const a = new THREE.Vector3(...parent.position);
        const b = new THREE.Vector3(...node.position);
        const lift = 0.5 + parent.finding.severity_score * 1.6;
        const mid = a
          .clone()
          .add(b)
          .multiplyScalar(0.5)
          .setY(lift + 0.9);
        const curve = new THREE.QuadraticBezierCurve3(
          a.clone().setY(lift),
          mid,
          b.clone().setY(0.4 + node.finding.severity_score * 1.6),
        );
        return (
          <Line
            color={pathLit ? C_PERMANENT_BAD : "#33405240"}
            dashed={!pathLit}
            dashScale={pathLit ? 1 : 4}
            key={`${parent.finding.id}:${node.finding.id}`}
            lineWidth={pathLit ? 2.6 : 1}
            opacity={pathLit ? 0.9 : 0.3}
            points={curve.getPoints(24)}
            transparent
          />
        );
      })}

      {nodes
        .filter((item) => item.finding.hop_depth !== 0)
        .map((item) => (
          <RiskNode
            item={item}
            key={item.finding.id}
            onSelect={() => onSelect(item.finding)}
            refused={Boolean(refusedIds?.has(item.finding.id))}
            remediated={Boolean(remediatedIds?.has(item.finding.id))}
            selected={item.finding.id === selectedId}
          />
        ))}

      <OrbitControls
        autoRotate={!selectedId}
        autoRotateSpeed={0.28}
        dampingFactor={0.06}
        enableDamping
        maxDistance={30}
        maxPolarAngle={Math.PI / 2.15}
        minDistance={6}
        target={[0, 0.8, 0]}
      />
    </>
  );
}

function Scene3DComponent({
  findings,
  attackPaths,
  selectedId,
  remediatedIds,
  refusedIds,
  hiddenIds,
  onSelect,
}: Scene3DProps) {
  const [webglOk] = useState(() => supportsWebGL());
  const visible = findings.filter(
    (finding) =>
      !hiddenIds?.has(finding.id) &&
      finding.verification_state !== "rejected" &&
      finding.verification_state !== "contradicted",
  );

  return (
    <div className="mirror-scene" aria-label="Interactive 3D exposure graph">
      {visible.length === 0 ? (
        <div className="scene-empty">
          <span className="pulse-orb" />
          <strong>Your verified identity is protected.</strong>
          <p>Approve an expansion to materialize findings here.</p>
        </div>
      ) : !webglOk ? (
        <SceneFallback findings={visible} />
      ) : (
        <ErrorBoundary fallback={<SceneFallback findings={visible} />}>
          <Canvas
            camera={{fov: 42, position: [0, 11, 16]}}
            dpr={[1, 1.75]}
            gl={{antialias: true, alpha: false}}
            shadows
          >
            <SceneContents
              attackPaths={attackPaths}
              findings={visible}
              onSelect={onSelect}
              refusedIds={refusedIds}
              remediatedIds={remediatedIds}
              selectedId={selectedId}
            />
          </Canvas>
        </ErrorBoundary>
      )}

      {/* A visualisation without a key is decoration. This states the encoding
          in the same words the rest of the interface uses. */}
      <div className="scene-legend scene-legend--v2">
        <span>
          <i style={{background: C_REVERSIBLE}} />
          Reversible
        </span>
        <span>
          <i style={{background: C_IRREVERSIBLE}} />
          Permanent
        </span>
        <span className="legend-note">Height = severity · Rings = hops from you</span>
      </div>
    </div>
  );
}

export const Scene3D = memo(Scene3DComponent, (prev, next) => {
  return (
    prev.findings.length === next.findings.length &&
    prev.selectedId === next.selectedId &&
    prev.remediatedIds === next.remediatedIds &&
    prev.refusedIds === next.refusedIds &&
    prev.hiddenIds === next.hiddenIds &&
    prev.attackPaths.length === next.attackPaths.length &&
    prev.onSelect === next.onSelect
  );
});
