import {useEffect, useRef} from "react";
import maplibregl, {type Map, type Marker, type Popup} from "maplibre-gl";

import type {Entity} from "./api";

import "maplibre-gl/dist/maplibre-gl.css";

interface GeoPoint {
  entity: Entity;
  lat: number;
  lng: number;
  confidence: number;
}

function extractGeo(entity: Entity): GeoPoint | null {
  const attrs = entity.attributes;
  const lat = Number(attrs["geo.latitude"] ?? attrs["latitude"] ?? attrs["lat"]);
  const lng = Number(
    attrs["geo.longitude"] ?? attrs["longitude"] ?? attrs["lng"],
  );
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  const confidence = Number(attrs.detector_confidence ?? 0);
  return {entity, lat, lng, confidence};
}

function markerColor(confidence: number) {
  if (confidence > 0.7) return "#22c55e";
  if (confidence > 0.4) return "#eab308";
  return "#ef4444";
}

interface MapViewProps {
  observations: Entity[];
}

export function MapView({observations}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const points = observations
      .map(extractGeo)
      .filter((p): p is GeoPoint => p !== null);

    const map = new maplibregl.Map({
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
            id: "osm-tiles",
            type: "raster",
            source: "osm",
            minzoom: 0,
            maxzoom: 19,
          },
        ],
      },
      center:
        points.length > 0 ? [points[0].lng, points[0].lat] : [0, 0],
      zoom: points.length > 1 ? 4 : 10,
    });

    mapRef.current = map;

    const markers: Marker[] = [];
    const popups: Popup[] = [];

    map.on("load", () => {
      points.forEach((point) => {
        const color = markerColor(point.confidence);
        const markerEl = document.createElement("div");
        markerEl.className = "map-marker";
        markerEl.style.background = color;
        markerEl.title = point.entity.attributes.label || "Observation";

        const popup = new maplibregl.Popup({offset: 18}).setHTML(
          `<div class="map-popup">
            <span class="map-popup-label">${escapeHtml(
              point.entity.attributes.label || "Unlabelled observation",
            )}</span>
            <span class="map-popup-confidence">
              ${Math.round(point.confidence * 100)}% confidence
            </span>
            <span class="map-popup-coords">
              ${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}
            </span>
          </div>`,
        );

        const marker = new maplibregl.Marker({element: markerEl})
          .setLngLat([point.lng, point.lat])
          .setPopup(popup)
          .addTo(map);

        markers.push(marker);
        popups.push(popup);
      });

      if (points.length > 1) {
        const lngs = points.map((p) => p.lng);
        const lats = points.map((p) => p.lat);
        const bounds = [
          [Math.min(...lngs), Math.min(...lats)],
          [Math.max(...lngs), Math.max(...lats)],
        ] as [[number, number], [number, number]];
        map.fitBounds(bounds, {padding: 60});
      }
    });

    return () => {
      markers.forEach((m) => m.remove());
      popups.forEach((p) => p.remove());
      map.remove();
      mapRef.current = null;
    };
  }, [observations]);

  return <div className="map-container" ref={containerRef} />;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
