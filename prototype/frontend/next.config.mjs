/** @type {import('next').NextConfig} */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  // Same-origin API: /api/* is proxied to FastAPI (uvicorn :8000, or API_ORIGIN).
  // Keeps the demo single-origin (no CORS surprises in a live pitch) and lets
  // phones and tablets on the same Wi-Fi reach everything through port 3000.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
    ];
  },
  // No Next.js dev badge on screen during a projected demo.
  devIndicators: false,
};

export default nextConfig;
