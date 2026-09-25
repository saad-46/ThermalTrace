import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Unit/component tests live in src/; Playwright E2E (e2e/) runs separately via `npm run test:e2e`.
export default defineConfig({
  plugins: [react()],
  test: { include: ["src/**/*.test.{ts,tsx}"], environment: "node" },
});
