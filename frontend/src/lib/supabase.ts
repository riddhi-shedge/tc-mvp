import { createClient } from "@supabase/supabase-js";

// Anon key only — safe solely because row-level security is on (deny-by-default
// until the Phase 7 tier policies). Never the service-role key here.
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);
