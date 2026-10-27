"use client";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { motion } from "framer-motion";
import { FileText, Trash2, Calendar, Filter, Plus, Loader2 } from "lucide-react";
import { useState, useEffect } from "react";
import Link from "next/link";

import API_BASE from "@/lib/apiBase";

interface Report {
    id: number;
    title: string;
    description: string | null;
    filter_state: Record<string, any>;
    ai_commentary: string | null;
    created_at: string;
    updated_at: string;
}

export default function ReportsPage() {
    const [reports, setReports] = useState<Report[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    const fetchReports = async () => {
        setIsLoading(true);
        const token = localStorage.getItem("token");
        try {
            const res = await fetch(`${API_BASE}/api/reports`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                setReports(await res.json());
            }
        } catch (e) {
            console.error("Failed to fetch reports:", e);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => { fetchReports(); }, []);

    const deleteReport = async (id: number) => {
        const token = localStorage.getItem("token");
        try {
            const res = await fetch(`${API_BASE}/api/reports/${id}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) setReports(prev => prev.filter(r => r.id !== id));
        } catch (e) {
            console.error("Delete failed:", e);
        }
    };

    const formatFilterSummary = (fs: Record<string, any>) => {
        const parts: string[] = [];
        if (fs.towns?.length) parts.push(fs.towns.slice(0, 3).join(", "));
        if (fs.flat_types?.length) parts.push(fs.flat_types.join(", "));
        if (fs.date_from || fs.date_to) parts.push(`${fs.date_from || "..."} – ${fs.date_to || "..."}`);
        return parts.join(" · ") || "All data";
    };

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />
                <div className="max-w-5xl mx-auto pt-28 px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between items-end mb-8">
                        <div>
                            <span className="text-accent font-bold uppercase tracking-widest text-xs">Reports Repository</span>
                            <h1 className="text-3xl font-extrabold tracking-tight mt-1">Analysis Reports</h1>
                            <p className="text-sm text-foreground/50 mt-1">
                                Save and revisit your analytics snapshots. Reports refresh with the latest data.
                            </p>
                        </div>
                        <Link
                            href="/analytics"
                            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold bg-accent text-white hover:bg-accent/90 transition-all"
                        >
                            <Plus className="w-4 h-4" />
                            New Analysis
                        </Link>
                    </div>

                    {isLoading ? (
                        <div className="h-64 flex items-center justify-center">
                            <Loader2 className="w-8 h-8 animate-spin text-accent" />
                        </div>
                    ) : reports.length === 0 ? (
                        <div className="text-center py-24">
                            <FileText className="w-16 h-16 mx-auto mb-4 text-foreground/15" />
                            <h2 className="text-xl font-bold mb-2 text-foreground/40">No reports yet</h2>
                            <p className="text-sm text-foreground/30 mb-6">
                                Go to Analytics, explore the data, and save your findings as a report.
                            </p>
                            <Link
                                href="/analytics"
                                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-bold bg-accent text-white hover:bg-accent/90 transition-all"
                            >
                                <Plus className="w-4 h-4" />
                                Start Exploring
                            </Link>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {reports.map((report, idx) => (
                                <motion.div
                                    key={report.id}
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: idx * 0.05 }}
                                >
                                    <Link href={`/reports/${report.id}`} className="block">
                                        <div className="glass rounded-2xl p-5 shadow-md border-foreground/5 hover:shadow-lg hover:border-accent/20 transition-all group cursor-pointer">
                                            <div className="flex items-start justify-between mb-3">
                                                <div className="flex items-center gap-3">
                                                    <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                                                        <FileText className="w-5 h-5 text-accent" />
                                                    </div>
                                                    <div>
                                                        <h3 className="font-bold text-sm group-hover:text-accent transition-colors">
                                                            {report.title}
                                                        </h3>
                                                        <div className="flex items-center gap-1 text-[10px] text-foreground/40 mt-0.5">
                                                            <Calendar className="w-3 h-3" />
                                                            {report.created_at ? new Date(report.created_at).toLocaleDateString() : "—"}
                                                        </div>
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); deleteReport(report.id); }}
                                                    className="p-2 rounded-lg text-foreground/20 hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100"
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                </button>
                                            </div>

                                            <div className="flex items-center gap-1.5 mb-3">
                                                <Filter className="w-3 h-3 text-foreground/30" />
                                                <span className="text-xs text-foreground/50 truncate">
                                                    {formatFilterSummary(report.filter_state)}
                                                </span>
                                            </div>

                                            {report.ai_commentary && (
                                                <p className="text-xs text-foreground/50 line-clamp-2 leading-relaxed">
                                                    {report.ai_commentary}
                                                </p>
                                            )}

                                            <div className="mt-3 pt-3 border-t border-foreground/5">
                                                <span className="text-[10px] font-bold text-accent uppercase tracking-wider">
                                                    View Live Report →
                                                </span>
                                            </div>
                                        </div>
                                    </Link>
                                </motion.div>
                            ))}
                        </div>
                    )}
                </div>
            </main>
        </RequireAuth>
    );
}
