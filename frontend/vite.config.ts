import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as { version: string };

// In development the API runs separately on :8787 (npm run dev at the project root starts both).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // every build gets its own id, which clears the answers saved in the browser: a new build may shape them differently
  define: { __APP_VERSION__: JSON.stringify(`${version}+${Date.now().toString(36)}`) },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8787" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
