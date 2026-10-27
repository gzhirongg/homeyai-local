"use client";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { motion } from "framer-motion";
import {
    AreaChart, Area, BarChart, Bar, LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import ChatDrawer from "@/components/ChatDrawer";
import {
    ArrowLeft, RefreshCw, Sparkles, Calendar, Filter, Loader2,
    TrendingUp, BarChart3, Building2, MessageSquare,
} from "lucide-react";
import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

export default function ReportDetailPage() {
    const params = useParams();
    const router = useRouter();
    const { user, isPremiumExperience: isPremium } = useAuth();
    const reportId = params.id;

    const [report, setReport] = useState<any>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshingInsight, setIsRefreshingInsight] = useState(false);
    const [chatOpen, setChatOpen] = useState(false);

    const fetchReport = async () => {
        setIsLoading(true);
        const token = localStorage.getItem("token");
        try {
            const res = await fetch(`${API_BASE}/api/reports/${reportId}`, {
                headers: subscriptionAwareHeaders(token),
            });
            if (res.ok) {
                setReport(await res.json());
            } else {
                router.push("/reports");
            }
        } catch (e) {
            console.error("Failed to fetch report:", e);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => { fetchReport(); }, [reportId]);

    const refreshInsight = async () => {
        if (!isPremium || !report?.live_data) return;
        setIsRefreshingInsight(true);
        try {
            const token = localStorage.getItem("token");
            const res = await fetch(`${API_BASE}/api/analytics/insight`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    filter_state: report.filter_state,
                    data_summary: report.live_data,
                }),
            });
            if (res.ok) {
                const json = await res.json();
                setReport((prev: any) => ({ ...prev, ai_commentary: json.insight }));
            }
        } catch (e) {
            console.error("Insight refresh failed:", e);
        } finally {
            setIsRefreshingInsight(false);
        }
    };

    const TAB_LABELS: Record<string, string> = {
        explorer: "Resale Data",
        sentiment: "Market Sentiment",
        chat: "AI Chat",
    };

    const formatFilterSummary = (fs: Record<string, any>) => {
        const parts: string[] = [];
        if (fs.selected_ura_region && fs.selected_ura_region !== "All Regions (Experimental)") {
            parts.push(`URA region: ${fs.selected_ura_region}`);
        }
        if (fs.active_tab) {
            parts.push(`Tab: ${TAB_LABELS[fs.active_tab] ?? fs.active_tab}`);
        }
        if (fs.towns?.length) parts.push(`Towns: ${fs.towns.join(", ")}`);
        if (fs.flat_types?.length) parts.push(`Types: ${fs.flat_types.join(", ")}`);
        if (fs.date_from || fs.date_to) parts.push(`Period: ${fs.date_from || "..."} – ${fs.date_to || "..."}`);
        if (fs.floor_levels?.length) parts.push(`Floors: ${fs.floor_levels.join(", ")}`);
        return parts;
    };

    const liveData = report?.live_data;
    const summary = liveData?.summary;
    const timeSeries = liveData?.time_series || [];
    const byTown = liveData?.by_town || [];
    const byFlatType = liveData?.by_flat_type || [];

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />
                <div className="max-w-6xl mx-auto pt-28 px-4 sm:px-6 lg:px-8">
                    {isLoading ? (
                        <div className="h-64 flex items-center justify-center">
                            <Loader2 className="w-8 h-8 animate-spin text-accent" />
                        </div>
                    ) : report ? (
                        <div className="space-y-6">
                            {/* Header */}
                            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                                <div>
                                    <button
                                        onClick={() => router.push("/reports")}
                                        className="flex items-center gap-1 text-xs font-bold text-foreground/40 hover:text-accent transition-colors mb-2"
                                    >
                                        <ArrowLeft className="w-3 h-3" /> Back to Reports
                                    </button>
                                    <h1 className="text-2xl font-extrabold tracking-tight">{report.title}</h1>
                                    <div className="flex items-center gap-3 mt-1.5">
                                        <span className="flex items-center gap-1 text-xs text-foreground/40">
                                            <Calendar className="w-3 h-3" />
                                            Created {report.created_at ? new Date(report.created_at).toLocaleDateString() : "—"}
                                        </span>
                                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-secondary/10 text-secondary font-bold uppercase">
                                            Live Data
                                        </span>
                                    </div>
                                </div>
                                <div className="flex gap-3">
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (!isPremium) {
                                                router.push("/profile");
                                                return;
                                            }
                                            setChatOpen(true);
                                        }}
                                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-gradient-to-r from-accent to-secondary text-white hover:opacity-90 transition-all"
                                    >
                                        <MessageSquare className="w-4 h-4" /> Chat About This
                                        {!isPremium && (
                                            <span className="text-[10px] font-bold uppercase opacity-80">Premium</span>
                                        )}
                                    </button>
                                    <button
                                        onClick={fetchReport}
                                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-white/50 backdrop-blur-md border border-foreground/10 hover:bg-white transition-all"
                                    >
                                        <RefreshCw className="w-4 h-4" /> Refresh Data
                                    </button>
                                </div>
                            </div>

                            {/* Filter tags */}
                            {report.filter_state && (
                                <div className="flex flex-wrap items-center gap-2">
                                    <Filter className="w-4 h-4 text-foreground/30" />
                                    {formatFilterSummary(report.filter_state).map((part, i) => (
                                        <span key={i} className="px-3 py-1 rounded-lg bg-foreground/5 text-xs font-medium text-foreground/60">
                                            {part}
                                        </span>
                                    ))}
                                </div>
                            )}

                            {/* AI Commentary */}
                            {report.ai_commentary && (
                                <motion.div
                                    initial={{ opacity: 0, y: -10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="glass rounded-2xl p-6 shadow-lg border-accent/20 border bg-gradient-to-r from-accent/5 to-secondary/5"
                                >
                                    <div className="flex items-start justify-between mb-3">
                                        <div className="flex items-center gap-2">
                                            <Sparkles className="w-5 h-5 text-accent" />
                                            <h3 className="font-bold text-sm">AI Insight</h3>
                                        </div>
                                        {isPremium ? (
                                            <button
                                                type="button"
                                                onClick={refreshInsight}
                                                disabled={isRefreshingInsight}
                                                className="flex items-center gap-1 text-xs font-bold text-accent hover:text-accent/70 transition-colors"
                                            >
                                                {isRefreshingInsight ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                                Re-generate
                                            </button>
                                        ) : null}
                                    </div>
                                    <p className="text-sm leading-relaxed text-foreground/80">{report.ai_commentary}</p>
                                </motion.div>
                            )}

                            {summary && (
                                <>
                                    {/* Stats */}
                                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                                        {[
                                            { label: "Total Transactions", value: summary.total?.toLocaleString(), color: "text-accent" },
                                            { label: "Avg Price", value: `S$${summary.avg_price?.toLocaleString()}`, color: "text-foreground" },
                                            { label: "Avg PSF", value: `S$${Math.round(summary.avg_psf)}`, color: "text-secondary" },
                                            { label: "Min Price", value: `S$${summary.min_price?.toLocaleString()}`, color: "text-foreground/70" },
                                            { label: "Max Price", value: `S$${summary.max_price?.toLocaleString()}`, color: "text-foreground/70" },
                                        ].map((s, i) => (
                                            <div key={i} className="glass rounded-2xl p-4 shadow-md border-foreground/5">
                                                <p className="text-[10px] font-bold text-foreground/40 uppercase tracking-wider">{s.label}</p>
                                                <p className={`text-xl font-black mt-1 ${s.color}`}>{s.value}</p>
                                            </div>
                                        ))}
                                    </div>

                                    {/* Price Trend */}
                                    {timeSeries.length > 0 && (
                                        <div className="glass rounded-2xl p-6 shadow-lg border-foreground/5">
                                            <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                                                <TrendingUp className="w-5 h-5 text-accent" />
                                                Price Trend
                                            </h3>
                                            <div className="h-72">
                                                <ResponsiveContainer width="100%" height="100%">
                                                    <AreaChart data={timeSeries} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                                                        <defs>
                                                            <linearGradient id="colorPriceReport" x1="0" y1="0" x2="0" y2="1">
                                                                <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                                                                <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0} />
                                                            </linearGradient>
                                                        </defs>
                                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                                                        <XAxis dataKey="period" axisLine={false} tickLine={false} tick={{ fontSize: 11, opacity: 0.5 }} />
                                                        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11 }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                                                        <Tooltip contentStyle={{ borderRadius: "12px", border: "1px solid rgba(0,0,0,0.05)" }} formatter={(v: any) => [`S$${Number(v).toLocaleString()}`, "Avg Price"]} />
                                                        <Area type="monotone" dataKey="avg_price" stroke="var(--color-accent)" strokeWidth={2.5} fillOpacity={1} fill="url(#colorPriceReport)" />
                                                    </AreaChart>
                                                </ResponsiveContainer>
                                            </div>
                                        </div>
                                    )}

                                    {/* Volume & PSF */}
                                    {timeSeries.length > 0 && (
                                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                            <div className="glass rounded-2xl p-6 shadow-lg border-foreground/5">
                                                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                                                    <BarChart3 className="w-5 h-5 text-secondary" />
                                                    Volume
                                                </h3>
                                                <div className="h-52">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <BarChart data={timeSeries}>
                                                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                                                            <XAxis dataKey="period" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                                                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} />
                                                            <Tooltip contentStyle={{ borderRadius: "12px" }} />
                                                            <Bar dataKey="txn_count" fill="var(--color-secondary)" radius={[4, 4, 0, 0]} />
                                                        </BarChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </div>
                                            <div className="glass rounded-2xl p-6 shadow-lg border-foreground/5">
                                                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                                                    <TrendingUp className="w-5 h-5 text-accent" />
                                                    PSF Trend
                                                </h3>
                                                <div className="h-52">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <LineChart data={timeSeries}>
                                                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                                                            <XAxis dataKey="period" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                                                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                                                            <Tooltip contentStyle={{ borderRadius: "12px" }} formatter={(v: any) => [`S$${Number(v).toFixed(2)}`, "Avg PSF"]} />
                                                            <Line type="monotone" dataKey="avg_psf" stroke="var(--color-accent)" strokeWidth={2.5} dot={false} />
                                                        </LineChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Breakdowns */}
                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                        {byTown.length > 0 && (
                                            <div className="glass rounded-2xl p-6 shadow-lg border-foreground/5">
                                                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                                                    <Building2 className="w-5 h-5 text-accent" /> By Town
                                                </h3>
                                                <div className="h-64">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <BarChart data={byTown.slice(0, 10)} layout="vertical">
                                                            <CartesianGrid strokeDasharray="3 3" horizontal stroke="rgba(0,0,0,0.05)" vertical={false} />
                                                            <XAxis type="number" hide />
                                                            <YAxis dataKey="town" type="category" width={90} tick={{ fontSize: 10, fontWeight: 600 }} axisLine={false} tickLine={false} />
                                                            <Tooltip contentStyle={{ borderRadius: "12px" }} />
                                                            <Bar dataKey="txn_count" fill="var(--color-accent)" radius={[0, 6, 6, 0]} />
                                                        </BarChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </div>
                                        )}
                                        {byFlatType.length > 0 && (
                                            <div className="glass rounded-2xl p-6 shadow-lg border-foreground/5">
                                                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                                                    <BarChart3 className="w-5 h-5 text-secondary" /> By Flat Type
                                                </h3>
                                                <div className="h-64">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <BarChart data={byFlatType}>
                                                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                                                            <XAxis dataKey="flat_type" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
                                                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} />
                                                            <Tooltip contentStyle={{ borderRadius: "12px" }} />
                                                            <Bar dataKey="txn_count" fill="var(--color-secondary)" radius={[6, 6, 0, 0]} />
                                                        </BarChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    ) : null}
                </div>

                {isPremium ? (
                    <ChatDrawer
                        open={chatOpen}
                        onClose={() => setChatOpen(false)}
                        analyticsContext={report ? {
                            report_title: report.title,
                            filters: report.filter_state,
                            summary: liveData?.summary,
                        } : null}
                    />
                ) : null}
            </main>
        </RequireAuth>
    );
}
