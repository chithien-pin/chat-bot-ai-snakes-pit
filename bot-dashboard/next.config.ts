import type { NextConfig } from "next";

const API_BACKEND = process.env.API_BACKEND_URL || "http://127.0.0.1:8080";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BACKEND}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
