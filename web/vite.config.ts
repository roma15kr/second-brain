/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: false,
      manifest: {
        name: "Second brain",
        short_name: "Brain",
        description: "Your day, mail, chats and promises in one place",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#1d2330",
        theme_color: "#1d2330",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
        ],
      },
      injectManifest: { globPatterns: ["**/*.{js,css,html,png,svg}"] },
    }),
  ],
  server: { proxy: { "/api": "http://localhost:8001" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // some flows wait on real polling intervals (1.5 s); 5 s was too tight in a full run
    testTimeout: 15_000,
  },
});
