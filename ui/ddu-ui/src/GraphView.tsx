import {useEffect, useRef, useState} from "react";
import cytoscape, {type Core, type ElementDefinition} from "cytoscape";

import type {Entity, Relationship} from "./api";

const TYPE_COLORS: Record<string, string> = {
  PERSON: "#3b82f6",
  ACCOUNT: "#22c55e",
  OBSERVATION: "#9ca3af",
  LOCATION: "#f97316",
  ORGANIZATION: "#a855f7",
  DEVICE: "#06b6d4",
  EVENT: "#ec4899",
};

const DEFAULT_NODE_COLOR = "#111918";

function nodeColor(type: string) {
  return TYPE_COLORS[type] || DEFAULT_NODE_COLOR;
}

function nodeLabel(entity: Entity) {
  const label =
    entity.attributes.label ||
    entity.attributes.name ||
    entity.attributes.observation_type ||
    entity.type;
  return label.length > 28 ? `${label.slice(0, 25)}...` : label;
}

interface GraphViewProps {
  entities: Entity[];
  relationships: Relationship[];
}

export function GraphView({entities, relationships}: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const [selected, setSelected] = useState<Entity | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const entityById = new Map(entities.map((e) => [e.id, e]));
    const nodes: ElementDefinition[] = entities.map((entity) => ({
      data: {
        id: entity.id,
        label: nodeLabel(entity),
        type: entity.type,
        color: nodeColor(entity.type),
        rawType: entity.type,
      },
    }));

    const connectedIds = new Set<string>();
    const edges: ElementDefinition[] = relationships
      .filter(
        (rel) =>
          entityById.has(rel.source_entity_id) &&
          entityById.has(rel.target_entity_id),
      )
      .map((rel) => {
        connectedIds.add(rel.source_entity_id);
        connectedIds.add(rel.target_entity_id);
        return {
          data: {
            id: rel.id,
            source: rel.source_entity_id,
            target: rel.target_entity_id,
            label: rel.relationship_type.replaceAll("_", " ").toLowerCase(),
          },
        };
      });

    void connectedIds;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "data(label)",
            color: "#f4f1e8",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 4,
            "text-outline-color": "#111918",
            "text-outline-width": 2,
            width: 36,
            height: 36,
            "border-width": 2,
            "border-color": "#111918",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 4,
            "border-color": "#e6582b",
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#696d68",
            "target-arrow-color": "#696d68",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            color: "#9aa4a1",
            "text-rotation": "autorotate",
            "text-background-color": "#f4f1e8",
            "text-background-padding": "2px",
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        padding: 40,
        idealEdgeLength: 120,
        nodeRepulsion: 8000,
      },
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (event) => {
      const id = event.target.id();
      const entity = entityById.get(id);
      setSelected(entity || null);
    });

    cy.on("tap", (event) => {
      if (event.target === cy) {
        setSelected(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [entities, relationships]);

  return (
    <div className="graph-wrapper">
      <div className="graph-container" ref={containerRef} />
      <aside className={`graph-side-panel ${selected ? "open" : ""}`}>
        {selected ? (
          <EntityDetails entity={selected} onClose={() => setSelected(null)} />
        ) : (
          <div className="graph-side-empty">
            <p className="eyebrow">Node details</p>
            <p>Select a node to inspect its attributes.</p>
          </div>
        )}
      </aside>
    </div>
  );
}

function EntityDetails({
  entity,
  onClose,
}: {
  entity: Entity;
  onClose: () => void;
}) {
  return (
    <div className="entity-details">
      <div className="entity-details-header">
        <span className="type-tag" style={{background: nodeColor(entity.type)}}>
          {entity.type}
        </span>
        <button className="close-btn" onClick={onClose} aria-label="Close">
          X
        </button>
      </div>
      <strong className="entity-details-label">
        {entity.attributes.label ||
          entity.attributes.name ||
          "Unlabelled entity"}
      </strong>
      <code className="entity-details-id">{entity.id}</code>
      <dl className="entity-details-attrs">
        {Object.entries(entity.attributes).map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
