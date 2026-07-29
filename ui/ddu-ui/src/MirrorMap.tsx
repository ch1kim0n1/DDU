import {memo, useEffect, useMemo, useRef, useState} from "react";
import maplibregl, {type Map, type Marker} from "maplibre-gl";

import {ErrorBoundary} from "./ErrorBoundary";
import type {Finding} from "./mirror-types";

import "maplibre-gl/dist/maplibre-gl.css";

function hashUnit(value: string, offset: number) {
  let hash = 2166136261 + offset;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 1000;
}

function MapFallback({findings}: {findings: Finding[]}) {
  const geo = findings.filter((f) =>
    ["gps_exposure", "location_inference", "record_class", "object_exposure"].includes(f.type),
  );
  return (
    <div className="map-fallback">
      <strong>Map view unavailable</strong>
      <ul>
        {geo.map((finding) => (
          <li key={finding.id}>
            <strong>{finding.label}</strong>
            <small>{Math.round(finding.confidence * 100)}% confidence</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MirrorMapInner({
  findings,
  onSelect,
}: {
  findings: Finding[];
  onSelect: (finding: Finding) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const [tileError, setTileError] = useState(false);
  const points = useMemo(
    () =>
      findings
        .filter((finding) =>
          ["gps_exposure", "location_inference", "record_class", "object_exposure"].includes(
            finding.type,
          ),
        )
        .filter(
          (finding) =>
            finding.verification_state !== "rejected" &&
            finding.verification_state !== "contradicted",
        )
        .map((finding) => ({
          finding,
          lng: -97.75 + (hashUnit(finding.id, 1) - 0.5) * 0.55,
          lat: 30.27 + (hashUnit(finding.id, 2) - 0.5) * 0.42,
        })),
    [findings],
  );
  const useClusters = points.length > 20;

  useEffect(() => {
    if (!containerRef.current) return;
    const map: Map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "privacy-basemap",
            type: "raster",
            source: "osm",
            paint: {
              "raster-saturation": -0.85,
              "raster-brightness-max": 0.42,
              "raster-contrast": 0.3,
            },
          },
        ],
      },
      center: [-97.75, 30.27],
      zoom: 9.4,
    });
    mapRef.current = map;
    map.on("error", (event) => {
      const message = String(event.error || "");
      if (message.toLowerCase().includes("tile") || message.toLowerCase().includes("fetch")) {
        setTileError(true);
      }
    });

    const markers: Marker[] = [];
    const byId = new globalThis.Map(
      points.map((point) => [point.finding.id, point.finding] as const),
    );

    map.on("load", () => {
      if (useClusters) {
        map.addSource("findings", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: points.map(({finding, lng, lat}) => ({
              type: "Feature",
              properties: {id: finding.id, label: finding.label},
              geometry: {type: "Point", coordinates: [lng, lat]},
            })),
          },
          cluster: true,
          clusterMaxZoom: 14,
          clusterRadius: 40,
        });
        map.addLayer({
          id: "clusters",
          type: "circle",
          source: "findings",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#2d72d2",
            "circle-radius": ["step", ["get", "point_count"], 16, 10, 22, 25, 28],
          },
        });
        map.addLayer({
          id: "cluster-count",
          type: "symbol",
          source: "findings",
          filter: ["has", "point_count"],
          layout: {
            "text-field": "{point_count_abbreviated}",
            "text-size": 12,
          },
          paint: {"text-color": "#ffffff"},
        });
        map.addLayer({
          id: "unclustered",
          type: "circle",
          source: "findings",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": "#db2c6f",
            "circle-radius": 7,
            "circle-stroke-width": 1,
            "circle-stroke-color": "#fff",
          },
        });
        map.on("click", "clusters", (event) => {
          const features = map.queryRenderedFeatures(event.point, {layers: ["clusters"]});
          const clusterId = features[0]?.properties?.cluster_id;
          const source = map.getSource("findings") as maplibregl.GeoJSONSource;
          if (clusterId == null) return;
          void source.getClusterExpansionZoom(Number(clusterId)).then((zoom) => {
            if (zoom == null) return;
            const geometry = features[0]?.geometry;
            if (!geometry || geometry.type !== "Point") return;
            map.easeTo({center: geometry.coordinates as [number, number], zoom});
          });
        });
        map.on("click", "unclustered", (event) => {
          const id = event.features?.[0]?.properties?.id as string | undefined;
          const finding = id ? byId.get(id) : undefined;
          if (finding) onSelect(finding);
        });
      } else {
        points.forEach(({finding, lng, lat}) => {
          const element = document.createElement("button");
          element.className = `mirror-map-marker state-${finding.verification_state}`;
          element.type = "button";
          element.title = `${finding.label} - approximate, privacy-jittered location`;
          element.addEventListener("click", () => onSelect(finding));
          markers.push(
            new maplibregl.Marker({element})
              .setLngLat([lng, lat])
              .setPopup(
                new maplibregl.Popup({offset: 20}).setText(
                  `${finding.label}, ${Math.round(finding.confidence * 100)}% confidence`,
                ),
              )
              .addTo(map),
          );
        });
      }
    });

    return () => {
      markers.forEach((marker) => marker.remove());
      map.remove();
      mapRef.current = null;
    };
  }, [onSelect, points, useClusters]);

  return (
    <div className="mirror-map-shell">
      <div className="privacy-map-note">
        <strong>Privacy-safe spatial view</strong>
        <span>Exact coordinates remain redacted; markers are deliberately jittered.</span>
      </div>
      {tileError && (
        <div className="map-tile-banner" role="status">
          <span>Map tiles unavailable - showing data points only</span>
          <button
            type="button"
            onClick={() => {
              setTileError(false);
              mapRef.current?.getStyle() && mapRef.current?.setStyle(mapRef.current.getStyle());
            }}
          >
            Retry
          </button>
        </div>
      )}
      <div className="mirror-map" ref={containerRef} />
    </div>
  );
}

function MirrorMapRoot({
  findings,
  onSelect,
}: {
  findings: Finding[];
  onSelect: (finding: Finding) => void;
}) {
  return (
    <ErrorBoundary fallback={<MapFallback findings={findings} />}>
      <MirrorMapInner findings={findings} onSelect={onSelect} />
    </ErrorBoundary>
  );
}

export const MirrorMap = memo(MirrorMapRoot, (prev, next) => prev.findings === next.findings);
