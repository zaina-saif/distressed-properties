import type { NextConfig } from "next";

// NEXT_PUBLIC_API_URL is inlined at build time; without it the site would call
// http://127.0.0.1:8000 from visitors' browsers. Fail hosted (Vercel) builds early.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error("NEXT_PUBLIC_API_URL must be set to the backend's public URL for hosted builds.");
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
