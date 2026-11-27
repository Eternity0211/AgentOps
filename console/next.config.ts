import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    agentUpgrade: "security",
  },
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
