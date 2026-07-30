/**
 * Real continent geometry for the landing globe.
 *
 * Source is Natural Earth land at 110m, shipped by the `world-atlas` package
 * as TopoJSON — 55KB, so it bundles rather than needing a network fetch. A
 * texture image would have been the obvious alternative, but a dotted globe
 * reads as instrument rather than travel-brochure, matches the exposure graph's
 * visual language, and stays crisp at any DPI.
 *
 * Approach: rasterise the land polygons once into an offscreen canvas using a
 * plain equirectangular projection, then test sphere points against that
 * bitmap. Point-in-polygon against every ring for every sample would be
 * thousands of times slower for an identical result — the canvas fill rule is
 * doing the geometry for us, in C.
 */

import {feature} from "topojson-client";
import landTopo from "world-atlas/land-110m.json";

type Ring = [number, number][];
type Geometry =
  | {type: "Polygon"; coordinates: Ring[]}
  | {type: "MultiPolygon"; coordinates: Ring[][]};

/** Equirectangular: linear in both axes, which is why no projection lib is needed. */
const MASK_W = 1024;
const MASK_H = 512;

let mask: {data: Uint8ClampedArray; w: number; h: number} | null = null;
let attempted = false;

function tracePolygon(ctx: CanvasRenderingContext2D, rings: Ring[]) {
  ctx.beginPath();
  for (const ring of rings) {
    ring.forEach(([lon, lat], index) => {
      const x = ((lon + 180) / 360) * MASK_W;
      const y = ((90 - lat) / 180) * MASK_H;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
  }
  // evenodd so inner rings (lakes) punch holes rather than filling solid.
  ctx.fill("evenodd");
}

function buildMask() {
  if (attempted) return mask;
  attempted = true;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_W;
    canvas.height = MASK_H;
    const ctx = canvas.getContext("2d", {willReadFrequently: true});
    if (!ctx) return null;

    ctx.fillStyle = "#000";
    // `feature` needs the object key from the topology; world-atlas calls it "land".
    const collection = feature(
      landTopo as never,
      (landTopo as unknown as {objects: {land: never}}).objects.land,
    ) as unknown as {geometry?: Geometry; features?: {geometry: Geometry}[]};

    const geometries: Geometry[] = collection.features
      ? collection.features.map((f) => f.geometry)
      : collection.geometry
        ? [collection.geometry]
        : [];

    for (const geometry of geometries) {
      if (geometry.type === "Polygon") tracePolygon(ctx, geometry.coordinates);
      else if (geometry.type === "MultiPolygon") {
        for (const polygon of geometry.coordinates) tracePolygon(ctx, polygon);
      }
    }

    mask = {data: ctx.getImageData(0, 0, MASK_W, MASK_H).data, w: MASK_W, h: MASK_H};
    return mask;
  } catch {
    // Any failure here (no DOM, blocked canvas, malformed topology) degrades to
    // a full sphere of dots rather than an empty globe.
    return null;
  }
}

function isLand(lat: number, lon: number): boolean {
  const m = buildMask();
  if (!m) return true;
  const x = Math.min(m.w - 1, Math.max(0, Math.floor(((lon + 180) / 360) * m.w)));
  const y = Math.min(m.h - 1, Math.max(0, Math.floor(((90 - lat) / 180) * m.h)));
  // Alpha channel: painted land is opaque, untouched ocean is transparent.
  return m.data[(y * m.w + x) * 4 + 3] > 128;
}

export type GlobePoints = {
  land: Float32Array;
  ocean: Float32Array;
};

/**
 * Even sphere sampling split into land and ocean sets.
 *
 * Fibonacci rather than lat/lon rings: rings bunch points at the poles, which
 * makes Antarctica look denser than Africa and gives away the projection.
 */
export function samplePoints(count: number, radius: number): GlobePoints {
  const land: number[] = [];
  const ocean: number[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;

    const px = Math.cos(theta) * r;
    const pz = Math.sin(theta) * r;

    const lat = Math.asin(y) * (180 / Math.PI);
    const lon = Math.atan2(pz, px) * (180 / Math.PI);

    const target = isLand(lat, lon) ? land : ocean;
    target.push(px * radius, y * radius, pz * radius);
  }

  return {land: new Float32Array(land), ocean: new Float32Array(ocean)};
}
