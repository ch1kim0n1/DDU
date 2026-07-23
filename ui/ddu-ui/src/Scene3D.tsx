import {useMemo, useState} from "react";

export interface SceneNode {
  id: string;
  label?: string;
  type?: string;
  x: number;
  y: number;
  z: number;
  confidence?: number;
}

export interface SceneEdge {
  id: string;
  source: string;
  target: string;
  type?: string;
  confidence?: number;
}

interface Scene3DProps {
  nodes: SceneNode[];
  edges: SceneEdge[];
}

function project(node: SceneNode, yaw: number, pitch: number) {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const x1 = node.x * cy - node.z * sy;
  const z1 = node.x * sy + node.z * cy;
  const y1 = node.y * cp - z1 * sp;
  const z2 = node.y * sp + z1 * cp;
  const depth = 220 / (220 + z2 + 80);
  return {x: 260 + x1 * depth, y: 160 + y1 * depth, depth, r: 5 + (node.confidence || 0.4) * 8};
}

export function Scene3D({nodes, edges}: Scene3DProps) {
  const [yaw, setYaw] = useState(0.4);
  const [pitch, setPitch] = useState(0.25);
  const projected = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.id, project(node, yaw, pitch)])),
    [nodes, yaw, pitch],
  );

  if (nodes.length === 0) {
    return <p className="panel-empty">No scene nodes yet. Run perception/intel first.</p>;
  }

  return (
    <div className="scene3d">
      <div className="scene3d-controls">
        <label>
          Yaw
          <input
            max={3.14}
            min={-3.14}
            onChange={(event) => setYaw(Number(event.target.value))}
            step={0.01}
            type="range"
            value={yaw}
          />
        </label>
        <label>
          Pitch
          <input
            max={1.2}
            min={-1.2}
            onChange={(event) => setPitch(Number(event.target.value))}
            step={0.01}
            type="range"
            value={pitch}
          />
        </label>
      </div>
      <svg className="scene3d-canvas" viewBox="0 0 520 320">
        {edges.map((edge) => {
          const a = projected[edge.source];
          const b = projected[edge.target];
          if (!a || !b) return null;
          return (
            <line
              key={edge.id}
              opacity={0.35 + (edge.confidence || 0.3) * 0.4}
              stroke="#111918"
              strokeWidth={1 + (edge.confidence || 0.3) * 2}
              x1={a.x}
              x2={b.x}
              y1={a.y}
              y2={b.y}
            />
          );
        })}
        {nodes.map((node) => {
          const p = projected[node.id];
          return (
            <g key={node.id}>
              <circle cx={p.x} cy={p.y} fill="#e6582b" opacity={0.85} r={p.r}>
                <animate attributeName="r" dur="2.4s" repeatCount="indefinite" values={`${p.r};${p.r + 2};${p.r}`} />
              </circle>
              <text fill="#111918" fontSize="10" x={p.x + 8} y={p.y + 3}>
                {(node.label || node.type || node.id).slice(0, 18)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
