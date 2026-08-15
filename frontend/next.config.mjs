/** @type {import('next').NextConfig} */
const nextConfig = {
  // Arena's live preview is served through an e2b.app proxy.
  allowedDevOrigins: ['*.e2b.app'],
  async rewrites() { return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }] },
  experimental: { optimizePackageImports: ['lucide-react'] },
};
export default nextConfig;