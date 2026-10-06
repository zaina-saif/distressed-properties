import type { NextConfig } from "next";

// NEXT_PUBLIC_* values are inlined at build time; without the API URL the site would
// call http://127.0.0.1:8000 from visitors' browsers. Fail hosted (Vercel) builds early.
// The Supabase pair is the public sign-in configuration (never the service-role key).
if (process.env.VERCEL) {
  const missing = ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"].filter((name) => !process.env[name]);
  if (missing.length) throw new Error(`Set ${missing.join(", ")} for hosted builds.`);
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
