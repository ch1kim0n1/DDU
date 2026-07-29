# Browser support — DDU Mirror

| Browser | Support |
|---------|---------|
| Chrome 120+ | Full (3D, WebSocket, camera, MapLibre, MediaPipe, speechSynthesis) |
| Firefox 120+ | Full except MediaPipe may fall back to Pass/Fail controls |
| Safari 17+ | Full; camera requires HTTPS; verify MediaPipe WASM |
| Edge 120+ | Full (Chromium; matches Chrome) |
| iOS Safari 17+ | Camera (HTTPS), 3D touch (`touch-action: none`), MediaPipe best-effort |
| Android Chrome 120+ | Same as iOS Safari |
| Not supported | IE 11, Chrome &lt; 100, Firefox &lt; 100, Safari &lt; 15 |

If WebGL is unavailable, the UI shows a 2D findings fallback and a notice to use Chrome, Firefox, Safari, or Edge.
