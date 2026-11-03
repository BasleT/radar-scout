import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  clearScreen: false,
  server: { port: 5173, strictPort: true, host: true },
  build: { target: "es2022", chunkSizeWarningLimit: 6000 },
});
