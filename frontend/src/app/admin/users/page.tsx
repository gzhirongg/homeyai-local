"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { useAuth } from "@/context/AuthContext";
import {
    ArrowLeft,
    Search,
    RefreshCw,
    Eye,
    Ban,
    ShieldCheck,
    Trash2,
    Loader2,
    UserCircle,
} from "lucide-react";

import API_BASE from "@/lib/apiBase";

type Usage = {
    saved_properties: number;
    analysis_reports: number;
    chat_conversations: number;
    chat_messages: number;
};

type AdminUserRow = {
    id: number;
    email: string;
    full_name: string;
    role: string;
    is_banned: boolean;
    remaining_valuations: number | null;
    usage: Usage;
};

const ROLES = ["guest", "free", "premium", "admin"] as const;

/** Role pill: background, text, border (light + dark tuned) */
function roleBadgeClasses(role: string): string {
    const r = role.toLowerCase();
    const map: Record<string, string> = {
        guest:
            "bg-slate-100 text-slate-700 border-slate-200/90",
        free: "bg-sky-100 text-sky-800 border-sky-200",
        premium:
            "bg-violet-100 text-violet-800 border-violet-200",
        admin:
            "bg-rose-100 text-rose-800 border-rose-300 shadow-sm shadow-rose-500/10",
    };
    return (
        map[r] ||
        "bg-foreground/10 text-foreground/80 border-foreground/15"
    );
}

function RoleBadge({ role }: { role: string }) {
    return (
        <span
            className={`inline-flex items-center px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider border ${roleBadgeClasses(role)}`}
        >
            {role}
        </span>
    );
}

function authHeaders(): HeadersInit {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    return { Authorization: `Bearer ${token}` };
}

export default function AdminUsersPage() {
    const { user: currentUser } = useAuth();
    const [rows, setRows] = useState<AdminUserRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [search, setSearch] = useState("");
    const [detail, setDetail] = useState<AdminUserRow | null>(null);
    const [actionError, setActionError] = useState("");
    const [pendingId, setPendingId] = useState<number | null>(null);

    const load = useCallback(async (query: string = "") => {
        setLoading(true);
        setError("");
        try {
            const url = query ? `${API_BASE}/api/admin/users?q=${encodeURIComponent(query)}` : `${API_BASE}/api/admin/users`;
            const res = await fetch(url, { headers: authHeaders() });
            if (!res.ok) {
                const j = await res.json().catch(() => ({}));
                throw new Error(j.detail || "Failed to load users");
            }
            setRows(await res.json());
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Failed to load users");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter(
            (r) =>
                r.email.toLowerCase().includes(q) ||
                r.full_name.toLowerCase().includes(q) ||
                r.role.toLowerCase().includes(q)
        );
    }, [rows, search]);

    async function patchUser(id: number, body: Record<string, unknown>) {
        setPendingId(id);
        setActionError("");
        try {
            const res = await fetch(`${API_BASE}/api/admin/users/${id}`, {
                method: "PATCH",
                headers: { ...authHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const j = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(j.detail || "Update failed");
            setRows((prev) => prev.map((r) => (r.id === id ? j : r)));
            setDetail((d) => (d && d.id === id ? j : d));
        } catch (e: unknown) {
            setActionError(e instanceof Error ? e.message : "Update failed");
        } finally {
            setPendingId(null);
        }
    }

    async function deleteUser(id: number) {
        if (!confirm("Permanently delete this account and all associated saved data?")) return;
        setPendingId(id);
        setActionError("");
        try {
            const res = await fetch(`${API_BASE}/api/admin/users/${id}`, {
                method: "DELETE",
                headers: authHeaders(),
            });
            const j = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(j.detail || "Delete failed");
            setRows((prev) => prev.filter((r) => r.id !== id));
            setDetail((d) => (d?.id === id ? null : d));
        } catch (e: unknown) {
            setActionError(e instanceof Error ? e.message : "Delete failed");
        } finally {
            setPendingId(null);
        }
    }

    return (
        <RequireAuth role="admin">
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />

                <div className="max-w-7xl mx-auto pt-28 px-4 sm:px-6 lg:px-8">
                    <Link
                        href="/admin"
                        className="inline-flex items-center gap-1 text-sm text-foreground/50 hover:text-foreground mb-6 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" /> Admin Dashboard
                    </Link>

                    <div className="mb-8">
                        <span className="text-red-500 font-bold uppercase tracking-widest text-xs">System Administration</span>
                        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight mt-2 flex flex-wrap items-center gap-3">
                            User management
                            <span className="text-sm font-medium px-2 py-1 bg-red-500/10 text-red-500 border border-red-500/20 rounded-md">
                                Accounts &amp; usage
                            </span>
                        </h1>
                        <p className="text-foreground/50 mt-2 text-sm max-w-2xl">
                            View account activity, adjust roles, suspend access, or remove users. Suspended users cannot sign in or call authenticated APIs.
                        </p>
                    </div>

                    <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between mb-6">
                        <div className="relative flex-1 max-w-md">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground/40" />
                            <input
                                type="search"
                                placeholder="Search email, name (Press Enter to search on server)"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') load(search);
                                }}
                                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-foreground/10 bg-white text-sm focus:ring-2 focus:ring-accent/30 focus:border-accent outline-none"
                            />
                        </div>
                        <button
                            type="button"
                            onClick={() => load(search)}
                            disabled={loading}
                            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-cyan-200/80 bg-gradient-to-br from-cyan-50 to-teal-50/80 text-cyan-900 text-sm font-semibold shadow-sm shadow-cyan-500/10 hover:from-cyan-100 hover:to-teal-100 hover:border-cyan-300/90 transition-all disabled:opacity-50"
                        >
                            <RefreshCw className={`w-4 h-4 text-cyan-600 ${loading ? "animate-spin" : ""}`} />
                            Refresh
                        </button>
                    </div>

                    {error && (
                        <div className="mb-4 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 text-sm">
                            {error}
                        </div>
                    )}
                    {actionError && (
                        <div className="mb-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-800 text-sm">
                            {actionError}
                        </div>
                    )}

                    <div className="glass rounded-2xl border border-foreground/5 shadow-xl overflow-hidden">
                        {loading && rows.length === 0 ? (
                            <div className="flex items-center justify-center py-24 text-foreground/50 gap-2">
                                <Loader2 className="w-5 h-5 animate-spin" /> Loading users…
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm text-left">
                                    <thead>
                                        <tr className="border-b border-foreground/10 bg-foreground/[0.02]">
                                            <th className="px-4 py-3 font-semibold">User</th>
                                            <th className="px-4 py-3 font-semibold">Role</th>
                                            <th className="px-4 py-3 font-semibold">Status</th>
                                            <th className="px-4 py-3 font-semibold hidden lg:table-cell">Usage</th>
                                            <th className="px-4 py-3 font-semibold hidden md:table-cell">Valuations left</th>
                                            <th className="px-4 py-3 font-semibold text-right">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filtered.map((r) => {
                                            const busy = pendingId === r.id;
                                            const isSelf = currentUser?.email === r.email;
                                            const u = r.usage;
                                            const usageLabel = `${u.saved_properties} saved · ${u.analysis_reports} reports · ${u.chat_conversations} chats`;
                                            return (
                                                <tr key={r.id} className="border-b border-foreground/5 hover:bg-foreground/[0.02]">
                                                    <td className="px-4 py-3">
                                                        <div className="font-medium">{r.full_name}</div>
                                                        <div className="text-foreground/50 text-xs">{r.email}</div>
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        <RoleBadge role={r.role} />
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        {r.is_banned ? (
                                                            <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-bold bg-red-100 text-red-800 border border-red-200">
                                                                <Ban className="w-3.5 h-3.5 shrink-0" /> Suspended
                                                            </span>
                                                        ) : (
                                                            <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                                                                <ShieldCheck className="w-3.5 h-3.5 shrink-0" /> Active
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3 text-foreground/60 text-xs hidden lg:table-cell max-w-[220px]">
                                                        {usageLabel}
                                                    </td>
                                                    <td className="px-4 py-3 hidden md:table-cell">
                                                        {r.remaining_valuations ?? "—"}
                                                    </td>
                                                    <td className="px-4 py-3 text-right whitespace-nowrap">
                                                        <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                                                            <button
                                                                type="button"
                                                                onClick={() => setDetail(r)}
                                                                className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-indigo-100 text-indigo-700 border border-indigo-200/90 hover:bg-indigo-200/80 hover:border-indigo-300 shadow-sm transition-colors"
                                                                title="View & manage"
                                                            >
                                                                <Eye className="w-4 h-4" />
                                                            </button>
                                                            <button
                                                                type="button"
                                                                disabled={busy || isSelf}
                                                                onClick={() => patchUser(r.id, { is_banned: !r.is_banned })}
                                                                className={
                                                                    r.is_banned
                                                                        ? "inline-flex items-center justify-center w-9 h-9 rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-200 hover:bg-emerald-200/70 disabled:opacity-30 transition-colors"
                                                                        : "inline-flex items-center justify-center w-9 h-9 rounded-lg bg-amber-100 text-amber-900 border border-amber-200 hover:bg-amber-200/70 disabled:opacity-30 transition-colors"
                                                                }
                                                                title={r.is_banned ? "Lift suspension" : "Suspend account"}
                                                            >
                                                                {busy ? (
                                                                    <Loader2 className="w-4 h-4 animate-spin" />
                                                                ) : r.is_banned ? (
                                                                    <ShieldCheck className="w-4 h-4" />
                                                                ) : (
                                                                    <Ban className="w-4 h-4" />
                                                                )}
                                                            </button>
                                                            <button
                                                                type="button"
                                                                disabled={busy || isSelf}
                                                                onClick={() => deleteUser(r.id)}
                                                                className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-rose-100 text-rose-700 border border-rose-200 hover:bg-rose-200/80 disabled:opacity-30 transition-colors"
                                                                title="Delete account"
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                                {filtered.length === 0 && !loading && (
                                    <p className="text-center py-12 text-foreground/50">No users match your search.</p>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {detail && (
                    <div
                        className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="user-detail-title"
                        onClick={() => setDetail(null)}
                    >
                        <div
                            className="bg-white rounded-2xl shadow-2xl border border-foreground/10 w-full max-w-lg max-h-[90vh] overflow-y-auto"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="p-6 border-b border-foreground/10 flex items-start gap-3">
                                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-violet-500/20 to-indigo-500/20 flex items-center justify-center text-violet-600 shrink-0 ring-2 ring-violet-500/20">
                                    <UserCircle className="w-7 h-7" />
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2 gap-y-1">
                                        <h2 id="user-detail-title" className="text-lg font-bold truncate">
                                            {detail.full_name}
                                        </h2>
                                        <RoleBadge role={detail.role} />
                                    </div>
                                    <p className="text-sm text-foreground/50 truncate">{detail.email}</p>
                                    <p className="text-xs text-foreground/40 mt-1">User ID · {detail.id}</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => setDetail(null)}
                                    className="text-sm text-foreground/50 hover:text-foreground px-2 py-1 rounded-lg hover:bg-foreground/5"
                                >
                                    Close
                                </button>
                            </div>

                            <div className="p-6 space-y-5">
                                <div>
                                    <p className="text-xs font-bold uppercase tracking-wider text-foreground/40 mb-2">Activity</p>
                                    <ul className="grid grid-cols-2 gap-2 text-sm">
                                        <li className="p-3 rounded-xl bg-blue-50/90 border border-blue-100">
                                            <span className="text-blue-600/80 text-xs font-medium block">Saved properties</span>
                                            <span className="font-bold text-lg text-blue-900">{detail.usage.saved_properties}</span>
                                        </li>
                                        <li className="p-3 rounded-xl bg-violet-50/90 border border-violet-100">
                                            <span className="text-violet-600/80 text-xs font-medium block">Analysis reports</span>
                                            <span className="font-bold text-lg text-violet-900">{detail.usage.analysis_reports}</span>
                                        </li>
                                        <li className="p-3 rounded-xl bg-teal-50/90 border border-teal-100">
                                            <span className="text-teal-600/80 text-xs font-medium block">Chat threads</span>
                                            <span className="font-bold text-lg text-teal-900">{detail.usage.chat_conversations}</span>
                                        </li>
                                        <li className="p-3 rounded-xl bg-orange-50/90 border border-orange-100">
                                            <span className="text-orange-600/80 text-xs font-medium block">Chat messages</span>
                                            <span className="font-bold text-lg text-orange-900">{detail.usage.chat_messages}</span>
                                        </li>
                                    </ul>
                                </div>

                                <div>
                                    <p className="text-xs font-bold uppercase tracking-wider text-foreground/40 mb-2">Role</p>
                                    <select
                                        value={detail.role}
                                        disabled={pendingId === detail.id || currentUser?.email === detail.email}
                                        onChange={(e) =>
                                            patchUser(detail.id, { role: e.target.value })
                                        }
                                        className="w-full px-3 py-2.5 rounded-xl border-2 border-violet-200 bg-violet-50/50 text-sm font-semibold text-violet-950 focus:ring-2 focus:ring-violet-400/40 focus:border-violet-400 outline-none disabled:opacity-50"
                                    >
                                        {ROLES.map((role) => (
                                            <option key={role} value={role}>
                                                {role}
                                            </option>
                                        ))}
                                    </select>
                                    {currentUser?.email === detail.email && (
                                        <p className="text-xs text-amber-600 mt-2">
                                            You cannot change your own role from this panel.
                                        </p>
                                    )}
                                </div>

                                <div className="flex flex-wrap gap-2">
                                    <button
                                        type="button"
                                        disabled={pendingId === detail.id || currentUser?.email === detail.email}
                                        onClick={() => patchUser(detail.id, { is_banned: !detail.is_banned })}
                                        className={
                                            detail.is_banned
                                                ? "flex-1 min-w-[140px] inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm border-2 border-emerald-300 bg-gradient-to-r from-emerald-500 to-teal-500 text-white shadow-md shadow-emerald-500/25 hover:from-emerald-600 hover:to-teal-600 disabled:opacity-40 transition-all"
                                                : "flex-1 min-w-[140px] inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm border-2 border-amber-300 bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/25 hover:from-amber-600 hover:to-orange-600 disabled:opacity-40 transition-all"
                                        }
                                    >
                                        {detail.is_banned ? (
                                            <>
                                                <ShieldCheck className="w-4 h-4" /> Lift suspension
                                            </>
                                        ) : (
                                            <>
                                                <Ban className="w-4 h-4" /> Suspend account
                                            </>
                                        )}
                                    </button>
                                    <button
                                        type="button"
                                        disabled={pendingId === detail.id || currentUser?.email === detail.email}
                                        onClick={() => {
                                            deleteUser(detail.id);
                                        }}
                                        className="flex-1 min-w-[140px] inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm border-2 border-rose-400 bg-gradient-to-r from-rose-600 to-red-600 text-white shadow-md shadow-rose-500/30 hover:from-rose-700 hover:to-red-700 disabled:opacity-40 transition-all"
                                    >
                                        <Trash2 className="w-4 h-4" /> Delete account
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </RequireAuth>
    );
}
