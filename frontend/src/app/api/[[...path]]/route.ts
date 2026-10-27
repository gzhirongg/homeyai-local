import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Hop-by-hop headers must not be forwarded (fetch will set its own where needed).
 */
const HOP_BY_HOP = new Set(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    ].map((h) => h.toLowerCase()),
);

/**
 * Node fetch auto-decompresses gzip bodies but leaves Content-Encoding on upstream.headers.
 * Forwarding both causes browsers to fail with ERR_CONTENT_DECODING_FAILED.
 */
const STRIP_UPSTREAM_RESPONSE = new Set(
    ["content-encoding", "content-length"].map((h) => h.toLowerCase()),
);

function backendOrigin(): string {
    const raw =
        process.env.BACKEND_INTERNAL_ORIGIN?.trim().replace(/\/$/, "") ||
        process.env.INTERNAL_API_ORIGIN?.trim().replace(/\/$/, "") ||
        "";
    return raw || "http://127.0.0.1:8000";
}

function buildTargetUrl(segments: string[] | undefined, search: string): string {
    const path = segments?.length ? segments.map((s) => encodeURIComponent(s)).join("/") : "";
    const base = `${backendOrigin()}/api`;
    return path ? `${base}/${path}${search}` : `${base}${search}`;
}

function proxyHeaders(incoming: Headers): Headers {
    const out = new Headers();
    incoming.forEach((value, key) => {
        if (!HOP_BY_HOP.has(key.toLowerCase())) {
            out.append(key, value);
        }
    });
    // Prefer uncompressed responses from FastAPI GZipMiddleware (fetch decompresses anyway).
    out.set("accept-encoding", "identity");
    return out;
}

function upstreamResponseHeaders(upstream: Headers): Headers {
    const out = new Headers();
    upstream.forEach((value, key) => {
        if (!STRIP_UPSTREAM_RESPONSE.has(key.toLowerCase())) {
            out.append(key, value);
        }
    });
    return out;
}

async function proxy(req: NextRequest, segments: string[] | undefined): Promise<Response> {
    const url = buildTargetUrl(segments, req.nextUrl.search);

    const init: RequestInit & { duplex?: string } = {
        method: req.method,
        headers: proxyHeaders(req.headers),
        redirect: "manual",
    };

    if (req.method !== "GET" && req.method !== "HEAD") {
        init.body = req.body;
        init.duplex = "half";
    }

    return fetch(url, init);
}

type RouteCtx = { params: Promise<{ path?: string[] }> };

async function dispatch(req: NextRequest, ctx: RouteCtx): Promise<NextResponse> {
    const { path } = await ctx.params;
    const upstream = await proxy(req, path);
    return new NextResponse(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: upstreamResponseHeaders(upstream.headers),
    });
}

export function GET(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}

export function POST(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}

export function PUT(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}

export function PATCH(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}

export function DELETE(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}

export function OPTIONS(req: NextRequest, ctx: RouteCtx) {
    return dispatch(req, ctx);
}
