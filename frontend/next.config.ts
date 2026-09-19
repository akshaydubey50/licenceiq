import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  devIndicators: false,
  // Keep Next.js inside this app even when an ancestor has an unrelated lockfile.
  turbopack: { root: __dirname },
};

export default nextConfig;
