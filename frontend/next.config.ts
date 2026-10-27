import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Production builds are a static export served by FastAPI from the same origin.
  output: isDev ? undefined : "export",
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // In `next dev`, forward API calls (including the SSE stream) to the backend.
  ...(isDev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
    },
  }),
};

export default nextConfig;
