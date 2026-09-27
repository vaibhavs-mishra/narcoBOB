import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // maplibre-gl ships its own web worker; Vite's dependency pre-bundling breaks the
  // worker URL, so let it load maplibre as-is.
  optimizeDeps: { exclude: ["maplibre-gl"] },
});
