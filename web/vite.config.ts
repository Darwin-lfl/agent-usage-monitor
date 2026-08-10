import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  base: "/",
  build: {
    outDir: "../src/agent_usage_monitor/web_dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("echarts") || id.includes("zrender")) return "charts";
          if (id.includes("node_modules")) return "vendor";
        },
      },
    },
  },
});
