import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Pin Turbopack's project root to this frontend package (fixes wrong-root inference when
// another lockfile exists higher in the filesystem, which can manifest as stray 404s in dev).
const rootDir =
    typeof __dirname !== "undefined"
        ? __dirname
        : path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
    turbopack: {
        root: rootDir,
    },
};

export default nextConfig;
