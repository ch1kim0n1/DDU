# Frontend bundle analysis — DDU Mirror

```bash
cd ui/ddu-ui
npm run bundle:analyze
```

Regenerate with:

```bash
cd ui/ddu-ui && npm run bundle:analyze -- -o ../../docs/bundle-analysis.html --open false
```

Treemap HTML: `docs/bundle-analysis.html`. Placeholder preview: `docs/bundle-analysis.png`.

## Composition (production build, Wave 3)

| Chunk | Approx gzip | Notes |
|-------|-------------|-------|
| `index` (shell) | ~72 KB | Initial route; under 300 KB target |
| `Scene3D` | ~287 KB | Three.js + R3F; lazy-loaded |
| `MirrorMap` | ~212 KB | MapLibre; lazy-loaded |
| `EvidenceDrawer` | ~106 KB | Includes recharts (used for severity/attribution charts) |
| `vision_bundle` | ~40 KB | MediaPipe path; lazy with Vision panel |

## Decisions

- **Three.js**: kept as namespace import for MeshStandardMaterial/Vector3 usage in Scene3D; loaded only when the 3D view mounts.
- **recharts**: **used** in EvidenceDrawer — keep.
- **MapLibre clustering**: enabled when geo findings &gt; 20.

Initial entry chunk remains the release gate; heavy deps stay behind `React.lazy`.
