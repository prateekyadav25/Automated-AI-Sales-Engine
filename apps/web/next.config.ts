import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@agrayian/sdk", "@agrayian/ui", "@agrayian/types"],
};

export default nextConfig;
