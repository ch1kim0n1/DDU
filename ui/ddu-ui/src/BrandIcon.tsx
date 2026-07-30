/**
 * Real platform marks.
 *
 * Paths come from `simple-icons` (CC0-1.0), so the shapes are the actual brand
 * marks rather than approximations, and each carries its official hex.
 *
 * LinkedIn is the one exception and is drawn here by hand. simple-icons does
 * not carry it — LinkedIn asked to be removed from the set over brand policy —
 * so shipping their exact mark from a redistributed asset would be going
 * against a request they made explicitly. The glyph below is a plain
 * professional-network mark in their blue, which communicates the platform
 * without redistributing the trademark.
 *
 * These identify services the product examines. That is descriptive use, not a
 * claim of partnership or endorsement, and nothing here should be read as one.
 */

import {BRAND_MARKS} from "./brand-marks";

export type BrandKey =
  | "linkedin"
  | "instagram"
  | "github"
  | "x"
  | "reddit"
  | "strava"
  | "facebook"
  | "email"
  | "steam"
  | "pinterest"
  | "twitch"
  | "records"
  | "photo";

type Mark = {title: string; hex: string; path: string};

/** Marks we draw ourselves — see the note at the top of this file. */
const CUSTOM: Partial<Record<BrandKey, Mark>> = {
  linkedin: {
    title: "LinkedIn",
    hex: "0A66C2",
    path:
      "M4.98 3.5C4.98 4.88 3.87 6 2.49 6S0 4.88 0 3.5 1.11 1 2.49 1 4.98 2.12 4.98 3.5zM.22 8.02h4.55V24H.22V8.02zm7.55 0h4.36v2.18h.06c.61-1.15 2.1-2.37 4.32-2.37 4.62 0 5.47 3.04 5.47 6.99V24h-4.55v-7.62c0-1.82-.03-4.16-2.53-4.16-2.54 0-2.93 1.98-2.93 4.03V24H7.77V8.02z",
  },
  // Not platforms — categories of exposure. Simple line glyphs so they read as
  // a different kind of thing from the brand marks beside them.
  records: {
    title: "Public records",
    hex: "8F99A8",
    path:
      "M3 2h13l5 5v15H3V2zm12 1.5V8h4.5L15 3.5zM6 11h12v1.6H6V11zm0 4h12v1.6H6V15zm0 4h8v1.6H6V19z",
  },
  photo: {
    title: "Photo",
    hex: "8F99A8",
    path:
      "M2 5h5l1.6-2h6.8L17 5h5v16H2V5zm10 3.6a5.4 5.4 0 1 0 0 10.8 5.4 5.4 0 0 0 0-10.8zm0 1.8a3.6 3.6 0 1 1 0 7.2 3.6 3.6 0 0 1 0-7.2z",
  },
};

function mark(key: BrandKey): Mark | null {
  return BRAND_MARKS[key] || CUSTOM[key] || null;
}

type Props = {
  brand: BrandKey;
  /** Pixel size of the square viewport. */
  size?: number;
  /**
   * Render in the brand's own colour. Off by default: on a near-black canvas a
   * row of saturated logos fights the interface, and several brand hexes
   * (GitHub #181717, X #000000, Steam #000000) are effectively invisible.
   */
  colored?: boolean;
  title?: string;
};

export function BrandIcon({brand, size = 18, colored = false, title}: Props) {
  const found = mark(brand);
  if (!found) return null;

  // Near-black marks need forcing to a legible tone even in "coloured" mode.
  const tooDark = ["181717", "000000", "0F0F0F"].includes(found.hex.toUpperCase());
  const fill = colored && !tooDark ? `#${found.hex}` : "currentColor";

  return (
    <svg
      aria-hidden={title ? undefined : true}
      fill={fill}
      height={size}
      role={title ? "img" : undefined}
      viewBox="0 0 24 24"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      {title ? <title>{title}</title> : null}
      <path d={found.path} />
    </svg>
  );
}

export function brandTitle(brand: BrandKey): string {
  return mark(brand)?.title || brand;
}
