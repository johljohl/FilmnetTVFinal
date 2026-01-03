import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Alla anrop som börjar med /stream.m3u8 skickas till Python
      "/stream.m3u8": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      // Alla anrop som slutar på .ts skickas till Python (använder regex)
      "^/.*\\.ts$": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
      // API anrop
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
