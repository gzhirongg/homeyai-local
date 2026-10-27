import type { ReactNode } from "react";

/**
 * Stable layout segment for every /admin/* route so the App Router always
 * nests admin pages consistently (helps Turbopack/discover nested routes).
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
    return <>{children}</>;
}
