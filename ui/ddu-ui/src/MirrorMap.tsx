import {useEffect, useMemo, useRef} from "react";
import maplibregl, {type Map, type Marker} from "maplibre-gl";

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

export function MirrorMap({
  findings,
  onSelect,
}: {
  findings: Finding[];
  onSelect: (finding: Finding) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
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
          // Privacy-safe, deliberately jittered demo coordinates. Exact values remain
          // behind the reveal-token endpoint and never enter MapLibre by default.
          lng: -97.75 + (hashUnit(finding.id, 1) - 0.5) * 0.55,
          lat: 30.27 + (hashUnit(finding.id, 2) - 0.5) * 0.42,
        })),
    [findings],
  );

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
    const markers: Marker[] = [];
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
    return () => {
      markers.forEach((marker) => marker.remove());
      map.remove();
    };
  }, [onSelect, points]);

  return (
    <div className="mirror-map-shell">
      <div className="privacy-map-note">
        <strong>Privacy-safe spatial view</strong>
        <span>Exact coordinates remain redacted; markers are deliberately jittered.</span>
      </div>
      <div className="mirror-map" ref={containerRef} />
    </div>
  );
}
