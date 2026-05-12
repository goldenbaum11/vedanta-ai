/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Emit a standalone server bundle so the production Docker image
  // can run `node server.js` without dragging the whole node_modules
  // tree along. See https://nextjs.org/docs/app/api-reference/next-config-js/output.
  output: "standalone",
};

export default nextConfig;
