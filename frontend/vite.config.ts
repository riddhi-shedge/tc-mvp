import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // B3 (deploy-readiness): a production bundle silently pointing at
  // http://localhost:8000 is a broken deploy that LOOKS built. Fail loudly.
  if (mode === "production") {
    for (const key of ["VITE_API_BASE", "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY"]) {
      if (!env[key]) {
        throw new Error(
          `Production build requires ${key} to be set (see frontend/.env.example). ` +
            "Refusing to bake a localhost fallback into a deployed bundle.",
        );
      }
    }
  }
  return { plugins: [react()] };
});
