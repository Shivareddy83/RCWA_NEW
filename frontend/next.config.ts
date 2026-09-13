import type { NextConfig } from 'next';

const backendUrl =
  process.env.BACKEND_INTERNAL_URL ||
  'https://rcaa-backend.yellowbay-bf9ef220.eastasia.azurecontainerapps.io';

const nextConfig: NextConfig = {
  output: 'standalone',

  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },

  async headers() {
    return [
      {
        source: '/signup',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-store, no-cache, must-revalidate',
          },
        ],
      },
    ];
  },
};

export default nextConfig;