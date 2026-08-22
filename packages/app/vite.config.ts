import { sentryVitePlugin } from "@sentry/vite-plugin"
import { defineConfig } from "vite"
import desktopPlugin from "./vite"

const sentry =
  process.env.SENTRY_AUTH_TOKEN && process.env.SENTRY_ORG && process.env.SENTRY_PROJECT
    ? sentryVitePlugin({
        authToken: process.env.SENTRY_AUTH_TOKEN,
        org: process.env.SENTRY_ORG,
        project: process.env.SENTRY_PROJECT,
        telemetry: false,
        release: {
          name: process.env.SENTRY_RELEASE ?? process.env.VITE_SENTRY_RELEASE,
        },
        sourcemaps: {
          assets: "./dist/**",
          filesToDeleteAfterUpload: "./dist/**/*.map",
        },
      })
    : false

export default defineConfig({
  plugins: [desktopPlugin, sentry] as any,
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    port: 3000,
  },
  optimizeDeps: {
    include: [
      "shiki",
      "marked-shiki",
      "marked",
      "@modelcontextprotocol/sdk/client/index.js",
      "@modelcontextprotocol/sdk/types.js",
      "@modelcontextprotocol/sdk/shared/transport.js",
      "effect",
      "luxon",
      "fuzzysort",
      "remeda",
      "diff",
      "@tanstack/solid-query",
      "@tanstack/solid-virtual",
      "@kobalte/core",
      "@solidjs/router",
      "@solidjs/meta",
    ],
  },
  build: {
    target: "esnext",
    sourcemap: true,
  },
})
