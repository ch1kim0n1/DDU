import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/intel": {
        target: "http://localhost:8120",
        changeOrigin: true,
        ws: true,
      },
      "/healthz": {
        target: "http://localhost:8120",
        changeOrigin: true,
      },
    },
  },
});
