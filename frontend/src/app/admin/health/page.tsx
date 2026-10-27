"use client";

import { useState, useEffect, useCallback } from "react";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import {
    CheckCircle,
    XCircle,
    Loader,
    RefreshCw,
    Wifi,
    Database,
    Cloud,
    Terminal,
    Clock,
    AlertTriangle,
    ArrowLeft,
    Workflow,
} from "lucide-react";

import API_BASE from "@/lib/apiBase";

/** Mirrors REMOTE_VM_IP from .env (see NEXT_PUBLIC_REMOTE_VM_IP in Docker Compose). */
const VM_IP = process.env.NEXT_PUBLIC_REMOTE_VM_IP?.trim() ?? "";

type ServiceStatus = "idle" | "loading" | "ok" | "error";

interface ServiceCheck {
    status: ServiceStatus;
    message: string;
}

interface HealthData {
    api: ServiceCheck;
    postgres: ServiceCheck;
    minio: ServiceCheck;
    prefect: ServiceCheck;
    environment?: {
        db_host: string;
        db_port: string;
        minio_endpoint: string;
        prefect_api_url: string;
    };
}

const IDLE_HEALTH: HealthData = {
    api: { status: "idle", message: "Not checked yet" },
    postgres: { status: "idle", message: "Not checked yet" },
    minio: { status: "idle", message: "Not checked yet" },
    prefect: { status: "idle", message: "Not checked yet" },
};

const LOADING_HEALTH: HealthData = {
    api: { status: "loading", message: "Checking…" },
    postgres: { status: "loading", message: "Checking…" },
    minio: { status: "loading", message: "Checking…" },
    prefect: { status: "loading", message: "Checking…" },
};

export default function SystemHealthPage() {
    const [health, setHealth] = useState<HealthData>(IDLE_HEALTH);
    const [isTesting, setIsTesting] = useState(false);
    const [lastChecked, setLastChecked] = useState<Date | null>(null);
    const [elapsed, setElapsed] = useState<number | null>(null);

    const runHealthCheck = useCallback(async () => {
        setIsTesting(true);
        setHealth(LOADING_HEALTH);
        const start = Date.now();

        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

        try {
            const controller = new AbortController();
            // 12 s client-side timeout — backend itself enforces 5 s per probe
            const timeoutId = setTimeout(() => controller.abort(), 12_000);

            const response = await fetch(`${API_BASE}/api/health`, {
                signal: controller.signal,
                headers: { Authorization: `Bearer ${token ?? ""}` },
            });

            clearTimeout(timeoutId);

            // 504 means the reverse-proxy / Docker reached the backend but the
            // backend itself timed out waiting for a service — treat as connection down.
            if (response.status === 504) {
                const timeoutMsg = VM_IP
                    ? `Connection Timeout (504) — Check that Tailscale is connected and the VM (${VM_IP}) is reachable`
                    : "Connection Timeout (504) — Check that the service containers are running and reachable";
                setHealth({
                    api: { status: "ok", message: "FastAPI backend is reachable" },
                    postgres: { status: "error", message: timeoutMsg },
                    minio: { status: "error", message: timeoutMsg },
                    prefect: { status: "error", message: timeoutMsg },
                });
                return;
            }

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            setHealth({
                api: data.api ?? { status: "ok", message: "Reachable" },
                postgres: data.postgres ?? { status: "error", message: "No response from backend" },
                minio: data.minio ?? { status: "error", message: "No response from backend" },
                prefect: data.prefect ?? { status: "error", message: "No response from backend" },
                environment: data.environment,
            });
        } catch (err: unknown) {
            const isTimeout = err instanceof Error && err.name === "AbortError";
            const msg = isTimeout
                ? "Request timed out — API is unreachable or very slow"
                : `API Unreachable: ${err instanceof Error ? err.message : String(err)}`;

            setHealth({
                api: { status: "error", message: msg },
                postgres: { status: "error", message: "Could not reach backend to test DB connection" },
                minio: { status: "error", message: "Could not reach backend to test MinIO connection" },
                prefect: { status: "error", message: "Could not reach backend to test Prefect connection" },
            });
        } finally {
            setIsTesting(false);
            setLastChecked(new Date());
            setElapsed(Date.now() - start);
        }
    }, []);

    // Run once on mount
    useEffect(() => {
        runHealthCheck();
    }, [runHealthCheck]);

    const allOk =
        health.api.status === "ok" &&
        health.postgres.status === "ok" &&
        health.minio.status === "ok" &&
        health.prefect.status === "ok";

    const anyError =
        health.api.status === "error" ||
        health.postgres.status === "error" ||
        health.minio.status === "error" ||
        health.prefect.status === "error";

    const dbEndpoint = health.environment
        ? `${health.environment.db_host}:${health.environment.db_port}`
        : "Configured PostgreSQL service";
    const minioEndpoint = health.environment?.minio_endpoint ?? "Configured MinIO service";
    const prefectEndpoint = health.environment?.prefect_api_url ?? "Configured Prefect service";

    return (
        <RequireAuth role="admin">
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />

                <div className="max-w-5xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                    {/* Back link */}
                    <a
                        href="/admin"
                        className="inline-flex items-center gap-1 text-sm text-foreground/50 hover:text-foreground mb-8 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" /> Admin Dashboard
                    </a>

                    {/* Page header */}
                    <div className="mb-10">
                        <span className="text-red-500 font-bold uppercase tracking-widest text-xs">
                            System Administration
                        </span>
                        <h1 className="text-4xl font-extrabold tracking-tight mt-2 flex items-center gap-3">
                            System Health Monitor
                        </h1>
                        <p className="text-foreground/50 mt-2 text-sm flex items-center gap-2 flex-wrap">
                            Real-time status of the API, database, storage, and workflow services.
                            {lastChecked && (
                                <span className="flex items-center gap-1 font-medium">
                                    <Clock className="w-3 h-3" />
                                    Last checked: {lastChecked.toLocaleTimeString()}
                                    {elapsed !== null && (
                                        <span className="text-foreground/40">({elapsed}ms)</span>
                                    )}
                                </span>
                            )}
                        </p>
                    </div>

                    {/* Overall banner */}
                    {!isTesting && lastChecked && (
                        <div
                            className={`mb-8 rounded-2xl p-4 flex items-center gap-3 border ${
                                allOk
                                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-700"
                                    : anyError
                                    ? "bg-red-500/10 border-red-500/30 text-red-700"
                                    : "bg-yellow-500/10 border-yellow-500/30 text-yellow-700"
                            }`}
                        >
                            {allOk ? (
                                <CheckCircle className="w-5 h-5 shrink-0" />
                            ) : anyError ? (
                                <AlertTriangle className="w-5 h-5 shrink-0" />
                            ) : (
                                <Loader className="w-5 h-5 shrink-0 animate-spin" />
                            )}
                            <span className="font-semibold text-sm">
                                {allOk
                                    ? "All systems operational — all services are reachable."
                                    : anyError
                                    ? "One or more services are unreachable. Check their status and configuration below."
                                    : "Checking connections…"}
                            </span>
                        </div>
                    )}

                    {/* Status cards */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                        <StatusCard
                            title="API Backend"
                            subtitle="FastAPI → Docker Container"
                            icon={<Wifi />}
                            check={health.api}
                            tunnelInfo={null}
                        />
                        <StatusCard
                            title="Database"
                            subtitle={dbEndpoint}
                            icon={<Database />}
                            check={health.postgres}
                            tunnelInfo={`PostgreSQL · ${dbEndpoint}`}
                        />
                        <StatusCard
                            title="MinIO (S3)"
                            subtitle={minioEndpoint}
                            icon={<Cloud />}
                            check={health.minio}
                            tunnelInfo={`MinIO API · ${minioEndpoint}`}
                        />
                        <StatusCard
                            title="Prefect Orchestration"
                            subtitle={prefectEndpoint}
                            icon={<Workflow />}
                            check={health.prefect}
                            tunnelInfo={`Prefect API · ${prefectEndpoint}`}
                        />
                    </div>

                    {/* Re-test button */}
                    <div className="flex justify-center mb-10">
                        <button
                            onClick={runHealthCheck}
                            disabled={isTesting}
                            className="bg-accent text-white px-8 py-3 rounded-xl font-bold text-base hover:shadow-lg transition-all disabled:opacity-50 flex items-center gap-2"
                        >
                            {isTesting ? (
                                <>
                                    <RefreshCw className="w-5 h-5 animate-spin" />
                                    Testing Connections…
                                </>
                            ) : (
                                <>
                                    <RefreshCw className="w-5 h-5" />
                                    Re-test Connection
                                </>
                            )}
                        </button>
                    </div>

                    {/* Environment audit */}
                    {health.environment && (
                        <div className="glass rounded-3xl p-8 shadow-xl border border-foreground/5 mb-8">
                            <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
                                <Terminal className="w-5 h-5 text-accent" />
                                Environment Audit
                            </h2>
                            <p className="text-sm text-foreground/50 mb-6">
                                Service addresses configured in the backend container.
                            </p>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                                <EnvCard
                                    label="DB Host"
                                    value={health.environment.db_host}
                                    expected={VM_IP}
                                    compare={Boolean(VM_IP)}
                                    hint={VM_IP ? "Should match REMOTE_VM_IP when using Tailscale" : "Database host reachable from the backend"}
                                />
                                <EnvCard
                                    label="DB Port"
                                    value={health.environment.db_port}
                                    expected="5432"
                                    hint="Direct port — no tunnel remapping needed"
                                />
                                <EnvCard
                                    label="MinIO Endpoint"
                                    value={health.environment.minio_endpoint}
                                    expected={VM_IP ? `${VM_IP}:9000` : ""}
                                    compare={Boolean(VM_IP)}
                                    hint="Storage API host and port reachable from the backend"
                                />
                                <EnvCard
                                    label="Prefect API"
                                    value={health.environment.prefect_api_url}
                                    expected=""
                                    compare={false}
                                    hint="Workflow API address reachable from the backend"
                                />
                            </div>
                        </div>
                    )}

                    {/* Tailscale quick-reference */}
                    {VM_IP && <div className="glass rounded-3xl p-8 shadow-xl border border-foreground/5">
                        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <Terminal className="w-5 h-5 text-accent" />
                            Tailscale Connection Reference
                        </h2>
                        <p className="text-sm text-foreground/50 mb-4">
                            No tunnel commands needed. Ensure Tailscale is running on your machine
                            before starting the dev environment.
                        </p>
                        <div className="space-y-3 font-mono text-sm">
                            <div className="p-4 rounded-xl bg-slate-900 text-green-400">
                                <span className="text-slate-400 select-none">
                                    # Verify Tailscale is connected and the VM is reachable
                                </span>
                                <br />
                                {VM_IP ? `ping -c 3 ${VM_IP}` : "ping -c 3 <REMOTE_VM_IP from .env>"}
                            </div>
                            <div className="p-4 rounded-xl bg-slate-900 text-green-400">
                                <span className="text-slate-400 select-none">
                                    # Check Tailscale daemon status
                                </span>
                                <br />
                                tailscale status
                            </div>
                        </div>
                        <p className="text-xs text-foreground/40 mt-4">
                            New team member? Install Tailscale at{" "}
                            <a
                                href="https://tailscale.com/download"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-accent underline"
                            >
                                tailscale.com/download
                            </a>{" "}
                            and ask the admin to approve your device.
                        </p>
                    </div>}
                </div>
            </main>
        </RequireAuth>
    );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: ServiceStatus }) {
    switch (status) {
        case "loading":
            return <Loader className="w-8 h-8 text-yellow-500 animate-spin" />;
        case "ok":
            return <CheckCircle className="w-8 h-8 text-emerald-500" />;
        case "error":
            return <XCircle className="w-8 h-8 text-red-500" />;
        default:
            return <div className="w-8 h-8 rounded-full border-2 border-slate-300" />;
    }
}

function StatusCard({
    title,
    subtitle,
    icon,
    check,
    tunnelInfo,
}: {
    title: string;
    subtitle: string;
    icon: React.ReactNode;
    check: ServiceCheck;
    tunnelInfo: string | null;
}) {
    const borderBg: Record<ServiceStatus, string> = {
        ok: "border-emerald-500/40 bg-emerald-500/5",
        error: "border-red-500/40 bg-red-500/5",
        loading: "border-yellow-500/40 bg-yellow-500/5",
        idle: "border-foreground/10",
    };

    const badgeStyle: Record<ServiceStatus, string> = {
        ok: "text-emerald-700 bg-emerald-500/15",
        error: "text-red-700 bg-red-500/15",
        loading: "text-yellow-700 bg-yellow-500/15",
        idle: "text-slate-500 bg-slate-500/10",
    };

    const label: Record<ServiceStatus, string> = {
        ok: "Connected",
        error: "Disconnected",
        loading: "Checking…",
        idle: "Idle",
    };

    return (
        <div
            className={`glass rounded-3xl p-6 border-2 transition-all duration-500 ${borderBg[check.status]}`}
        >
            <div className="flex items-start justify-between mb-4">
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent">
                    {icon}
                </div>
                <StatusIcon status={check.status} />
            </div>
            <h3 className="font-bold text-lg leading-tight">{title}</h3>
            <p className="text-xs text-foreground/50 mb-3">{subtitle}</p>
            <span className={`text-xs font-bold px-2 py-1 rounded-md ${badgeStyle[check.status]}`}>
                {label[check.status]}
            </span>
            {check.message && check.status !== "loading" && (
                <p className="text-xs text-foreground/60 mt-3 leading-relaxed break-words">
                    {check.message}
                </p>
            )}
            {tunnelInfo && (
                <p className="text-xs font-mono text-accent/70 mt-2">{tunnelInfo}</p>
            )}
        </div>
    );
}

function EnvCard({
    label,
    value,
    expected,
    hint,
    compare = true,
}: {
    label: string;
    value: string;
    expected: string;
    hint: string;
    compare?: boolean;
}) {
    const isCorrect = compare && value === expected;
    const neutral = !compare;
    return (
        <div
            className={`rounded-xl p-4 border ${
                neutral
                    ? "border-foreground/10 bg-slate-500/5"
                    : isCorrect
                      ? "border-emerald-500/30 bg-emerald-500/5"
                      : "border-orange-500/30 bg-orange-500/5"
            }`}
        >
            <p className="text-xs font-bold text-foreground/50 mb-1">{label}</p>
            <p
                className={`font-mono text-sm font-bold break-all ${
                    neutral ? "text-foreground/80" : isCorrect ? "text-emerald-600" : "text-orange-600"
                }`}
            >
                {value}
            </p>
            {compare && !isCorrect && (
                <p className="text-xs text-orange-500/80 mt-1">
                    Expected: <span className="font-mono">{expected}</span>
                </p>
            )}
            <p className="text-xs text-foreground/40 mt-2">{hint}</p>
        </div>
    );
}
