import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) return "vendor-react";
          if (id.includes("node_modules/motion")) return "vendor-motion";
          if (id.includes("node_modules/three")) return "vendor-three";
          if (id.includes("node_modules/@phosphor-icons")) return "vendor-icons";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5174,
  },
});
