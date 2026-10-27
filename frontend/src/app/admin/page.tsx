"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { Database, TrendingUp, Users, Activity, Settings, RefreshCw, Brain } from "lucide-react";
import API_BASE from "@/lib/apiBase";

export default function AdminDashboardPage() {
    const [isSyncing, setIsSyncing] = useState(false);
    const [totalUsers, setTotalUsers] = useState<number | null>(null);
    const [bannedCount, setBannedCount] = useState<number | null>(null);

    useEffect(() => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
        if (!token) return;
        fetch(`${API_BASE}/api/admin/metrics`, { headers: { Authorization: `Bearer ${token}` } })
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data && typeof data.total_users === "number") setTotalUsers(data.total_users);
                if (data && typeof data.banned_users === "number") setBannedCount(data.banned_users);
            })
            .catch(() => {});
    }, []);

    const handleSync = () => {
        setIsSyncing(true);
        setTimeout(() => setIsSyncing(false), 3000); // Mock sync
    };

    return (
        <RequireAuth role="admin">
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />
            
            <div className="max-w-7xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                <div className="mb-10 block">
                    <span className="text-red-500 font-bold uppercase tracking-widest text-xs">System Administration</span>
                    <h1 className="text-4xl font-extrabold tracking-tight mt-2 flex items-center gap-3">
                        Admin Dashboard
                        <span className="text-sm font-medium px-2 py-1 bg-red-500/10 text-red-500 border border-red-500/20 rounded-md flex items-center gap-1">
                            <Settings className="w-4 h-4" /> Restricted
                        </span>
                    </h1>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <StatCard
                        icon={<Users />}
                        title="Total Users"
                        value={totalUsers != null ? totalUsers.toLocaleString() : "—"}
                        trend={bannedCount != null && bannedCount > 0 ? `${bannedCount} suspended` : "Live from DB"}
                    />
                    <StatCard icon={<TrendingUp />} title="Valuations Gen" value="14,092" trend="+8%" />
                    <StatCard icon={<Database />} title="DB Records" value="1.2M" trend="Stable" />
                    <StatCard icon={<Activity />} title="System Load" value="24%" trend="Normal" />
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    {/* Data Sync Panel */}
                    <div className="glass rounded-3xl p-8 shadow-xl border-foreground/5 relative overflow-hidden">
                        <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">
                            <Database className="text-accent" /> Data Operations
                        </h2>
                        <p className="text-sm text-foreground/50 mb-6">
                            Data catalog, model management, system health, and user accounts are in the{" "}
                            <span className="font-semibold text-red-600">Admin</span> menu in the navigation bar.
                        </p>

                        <div className="space-y-6">
                            <div className="p-4 rounded-2xl bg-white/50 border border-foreground/5 flex items-center justify-between">
                                <div>
                                    <h3 className="font-bold">HDB Resale Data Sync</h3>
                                    <p className="text-sm text-foreground/50">Pull latest transactions from Data.gov.sg</p>
                                    <p className="text-xs font-semibold text-accent mt-2">Last Run: 2 hours ago</p>
                                </div>
                                <button 
                                    onClick={handleSync}
                                    disabled={isSyncing}
                                    className="bg-accent text-white px-4 py-2 rounded-xl font-bold hover:shadow-lg transition-all disabled:opacity-50 flex items-center gap-2"
                                >
                                    {isSyncing ? <><RefreshCw className="w-4 h-4 animate-spin" /> Syncing</> : "Trigger Sync"}
                                </button>
                            </div>

                            <div className="p-4 rounded-2xl bg-white/50 border border-foreground/5 flex items-center justify-between">
                                <div>
                                    <h3 className="font-bold">URA API Sync</h3>
                                    <p className="text-sm text-foreground/50">Pull private property transactions</p>
                                    <p className="text-xs font-semibold text-accent mt-2">Last Run: Yesterday</p>
                                </div>
                                <button className="bg-accent text-white px-4 py-2 rounded-xl font-bold hover:shadow-lg transition-all flex items-center gap-2">
                                    Trigger Sync
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Model management — full console linked from Admin menu */}
                    <div className="glass rounded-3xl p-8 shadow-xl border border-violet-500/15 bg-gradient-to-br from-violet-500/5 to-secondary/5 relative overflow-hidden flex flex-col justify-center">
                        <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">
                            <Brain className="text-violet-600 w-7 h-7" /> Model management
                        </h2>
                        <p className="text-sm text-foreground/55 mb-6 max-w-md">
                            Training runs, drift alerts, job history, and artifact notes live on a dedicated console (prototype UI).
                        </p>
                        <Link
                            href="/admin/models"
                            className="inline-flex items-center justify-center gap-2 w-full sm:w-auto px-5 py-3 rounded-xl bg-secondary text-white font-bold shadow-md hover:shadow-lg hover:bg-secondary/90 transition-all"
                        >
                            <Activity className="w-4 h-4" />
                            Open model console
                        </Link>
                    </div>
                </div>
            </div>
            </main>
        </RequireAuth>
    );
}

function StatCard({ icon, title, value, trend }: any) {
    return (
        <div className="glass rounded-xl p-6 border border-foreground/5">
            <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center text-accent mb-4">
                {icon}
            </div>
            <p className="text-sm text-foreground/50 font-medium mb-1">{title}</p>
            <h3 className="text-3xl font-black">{value}</h3>
            <p className="text-xs font-bold text-secondary mt-2">{trend}</p>
        </div>
    )
}
