import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The help pages are served by the API when it is started with HELP_DIR (see run_local.py).
    proxy: Object.fromEntries(["/api", "/help"].map((path) => [path, process.env.API_URL || "http://localhost:8000"])),
  },
});
