# Lighthouse targets — DDU Mirror UI

Run against the production build (`npm run build && npm run preview`):

| Category        | Target |
|-----------------|--------|
| Performance     | > 80   |
| Accessibility   | > 90   |
| Best Practices  | > 90   |
| SEO             | n/a (app, not marketing) |

## How to measure

```bash
cd ui/ddu-ui
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
# Chrome DevTools → Lighthouse → Desktop, clear storage
```

## Known trade-offs

- Initial JS is code-split (~70KB gzip for the shell). Three.js / MapLibre / MediaPipe load on demand and will lower Performance if audited with those panels open — that is expected.
- Activity stream uses a windowed render (last 40 filtered / 12 visible + search) instead of `react-window`. At demo scale this keeps scroll smooth without an extra dependency; adopt `react-window` if logs routinely exceed ~200 entries.
- Prefer `prefers-reduced-motion` paths already wired in CSS when scoring a11y.

Document scores in the PR that ships a UI release.
