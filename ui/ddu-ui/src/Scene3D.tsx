import {Line, OrbitControls, Text} from "@react-three/drei";
import {Canvas, useFrame} from "@react-three/fiber";
import {useEffect, useMemo, useRef, useState} from "react";
import * as THREE from "three";

import type {AttackPath, Finding} from "./mirror-types";

// Blueprint-derived palette: green3=confirmed, blue5=likely, orange3=hypothesis
const STATE_COLORS: Record<Finding["verification_state"], string> = {
  confirmed: "#238551",
  likely: "#8abbff",
  hypothesis: "#c87619",
  contradicted: "#9d3f9d",
  rejected: "#404854",
};

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

function layoutFindings(findings: Finding[]): LayoutNode[] {
  const byHop = new Map<number, Finding[]>();
  findings.forEach((finding) => {
    const bucket = byHop.get(finding.hop_depth) || [];
    bucket.push(finding);
    byHop.set(finding.hop_depth, bucket);
  });

  const output: LayoutNode[] = [];
  for (const [hop, bucket] of byHop) {
    bucket
      .sort((a, b) => b.severity_score - a.severity_score)
      .forEach((finding, index) => {
        const spread = Math.max(3.2, bucket.length * 1.1);
        const angle = (index / Math.max(1, bucket.length)) * Math.PI * 2 + hop * 0.7;
        const radius = hop === 0 ? 0 : 2.4 + hop * 0.7;
        const x = Math.cos(angle) * radius + (index - (bucket.length - 1) / 2) * 0.18;
        const z = hop * -3.1 + Math.sin(angle) * Math.min(spread, 2.4);
        output.push({
          finding,
          position: [x, 0, z],
        });
      });
  }
  return output;
}

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
  const glow = useRef<THREE.MeshStandardMaterial>(null);
  const [hovered, setHovered] = useState(false);
  const severity = item.finding.severity_score;
  const height = 0.55 + severity * 2.9;
  const baseColor = STATE_COLORS[item.finding.verification_state];

  useEffect(() => {
    if (group.current) group.current.scale.setScalar(0.001);
  }, []);

  useFrame((state, delta) => {
    if (!group.current) return;
    const target = remediated ? 0.88 : selected || hovered ? 1.12 : 1;
    group.current.scale.lerp(
      new THREE.Vector3(target, target, target),
      1 - Math.pow(0.001, delta),
    );
    if (refused) {
      group.current.rotation.y = Math.sin(state.clock.elapsedTime * 8) * 0.08;
    }
    if (glow.current) {
      glow.current.emissiveIntensity =
        remediated ? 0.03 : 0.25 + severity * 1.6 + (selected ? 0.8 : 0);
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
      <mesh position={[0, height / 2, 0]} castShadow>
        <cylinderGeometry args={[0.34, 0.48, height, 18]} />
        <meshStandardMaterial
          color={remediated ? "#2f343c" : baseColor}
          emissive={remediated ? "#000000" : baseColor}
          emissiveIntensity={0.6}
          metalness={0.5}
          ref={glow}
          roughness={0.28}
        />
      </mesh>
      <mesh position={[0, height + 0.08, 0]}>
        <sphereGeometry args={[0.42, 20, 20]} />
        <meshStandardMaterial
          color={remediated ? "#383e47" : baseColor}
          emissive={remediated ? "#000000" : baseColor}
          emissiveIntensity={remediated ? 0 : 0.9}
          roughness={0.22}
        />
      </mesh>
      {(selected || hovered) && (
        <Text
          anchorX="center"
          anchorY="bottom"
          color="#f6f7f9"
          fontSize={0.28}
          maxWidth={3.2}
          outlineColor="#111418"
          outlineWidth={0.025}
          position={[0, height + 0.72, 0]}
          textAlign="center"
        >
          {item.finding.label}
        </Text>
      )}
      {refused && (
        <Text
          color="#cd4246"
          fontSize={0.22}
          position={[0, 0.22, 0.56]}
          outlineColor="#111418"
          outlineWidth={0.02}
        >
          PERMANENT
        </Text>
      )}
    </group>
  );
}

function SceneContents({
  findings,
  attackPaths,
  selectedId,
  remediatedIds,
  refusedIds,
  onSelect,
}: Omit<Scene3DProps, "hiddenIds">) {
  const nodes = useMemo(() => layoutFindings(findings), [findings]);
  const byId = useMemo(
    () => new Map(nodes.map((node) => [node.finding.id, node])),
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
            activePathIds.has(node.finding.id) &&
            activePathIds.has(parent.finding.id);
          return {node, parent, pathLit};
        }),
    [activePathIds, byId, nodes],
  );

  return (
    <>
      <color attach="background" args={["#111418"]} />
      <fog attach="fog" args={["#111418", 11, 30]} />
      <ambientLight intensity={0.7} />
      <directionalLight castShadow intensity={2.2} position={[5, 12, 4]} />
      <pointLight color="#2d72d2" intensity={35} position={[-6, 5, -8]} />
      <gridHelper
        args={[34, 34, "#383e47", "#252a31"]}
        position={[0, -0.02, -5]}
      />
      {edges.map(({node, parent, pathLit}) => {
        const from = new THREE.Vector3(...parent.position).add(
          new THREE.Vector3(0, 0.4 + parent.finding.severity_score, 0),
        );
        const to = new THREE.Vector3(...node.position).add(
          new THREE.Vector3(0, 0.4 + node.finding.severity_score, 0),
        );
        return (
          <Line
            color={pathLit ? "#db2c6f" : "#383e47"}
            dashed={!pathLit}
            dashScale={pathLit ? 1 : 3}
            key={`${parent.finding.id}:${node.finding.id}`}
            lineWidth={pathLit ? 3.3 : 1.1}
            opacity={pathLit ? 0.95 : 0.42}
            points={[from, to]}
            transparent
          />
        );
      })}
      {nodes.map((item) => (
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
        autoRotateSpeed={0.3}
        dampingFactor={0.06}
        enableDamping
        maxDistance={24}
        maxPolarAngle={Math.PI / 2.05}
        minDistance={7}
        target={[0, 1.4, -4]}
      />
    </>
  );
}

export function Scene3D({
  findings,
  attackPaths,
  selectedId,
  remediatedIds,
  refusedIds,
  hiddenIds,
  onSelect,
}: Scene3DProps) {
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
      ) : (
        <Canvas
          camera={{fov: 46, position: [9, 9, 12]}}
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
      )}
      <div className="scene-axis" aria-hidden="true">
        <span>SEED</span>
        <i />
        <span>HOP DEPTH -&gt;</span>
      </div>
      <div className="scene-legend">
        {Object.entries(STATE_COLORS)
          .slice(0, 3)
          .map(([state, color]) => (
            <span key={state}>
              <i style={{background: color}} />
              {state}
            </span>
          ))}
      </div>
    </div>
  );
}
