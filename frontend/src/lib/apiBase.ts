/**
 * Browser base URL for FastAPI (`/api/...`).
 *
 * When `NEXT_PUBLIC_API_URL` is set to a non-empty string, fetch goes there directly (VM / split deploy).
 * When unset or empty, use same-origin `/api`; `src/app/api/[[...path]]/route.ts` proxies to FastAPI via
 * `BACKEND_INTERNAL_ORIGIN` so `Authorization` and other headers are forwarded.
 *
 * If the env points at localhost but the page is opened from another host (e.g. Tailscale IP), the
 * browser would call *that* machine's loopback — use same-origin proxy instead.
 */
function normalize(raw: string | undefined): string {
    const t = (raw ?? "").trim().replace(/\/$/, "");
    return t;
}

function isLoopbackApiUrl(raw: string): boolean {
    try {
        const u = new URL(raw);
        return u.hostname === "localhost" || u.hostname === "127.0.0.1";
    } catch {
        return false;
    }
}

function resolveApiBase(): string {
    const next = normalize(process.env.NEXT_PUBLIC_API_URL);
    if (next === "") return "";

    if (typeof window !== "undefined" && isLoopbackApiUrl(next)) {
        const h = window.location.hostname;
        if (h !== "localhost" && h !== "127.0.0.1") {
            return "";
        }
    }

    return next;
}

const API_BASE = resolveApiBase();

export default API_BASE;
