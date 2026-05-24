import type { NextConfig } from "next";
import { validateEnv } from "./lib/env-validator";

// Validate env at build/start time — fails fast on misconfiguration
validateEnv();

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "graph.microsoft.com" },
      { protocol: "https", hostname: "*.microsoft.com" },
    ],
  },
  experimental: {
    serverComponentsExternalPackages: ["bcryptjs", "@prisma/client"],
  },
};

export default nextConfig;
