import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react-dom") || id.includes("\\react\\") || id.includes("/react/")) return "react";
          if (id.includes("@tanstack")) return "query";
          if (id.includes("lucide-react")) return "icons";
          return undefined;
        }
      }
    }
  },
  server: {
    proxy: {
      "/health": "http://127.0.0.1:8002",
      "/research": "http://127.0.0.1:8002"
    }
  }
});
