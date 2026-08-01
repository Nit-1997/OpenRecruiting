import path from 'node:path';
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle so the Docker image does not need
  // node_modules at runtime.
  output: 'standalone',
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
