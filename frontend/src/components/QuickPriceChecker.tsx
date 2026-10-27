"use client";

import { useState } from "react";
import { Search, Loader2, Info } from "lucide-react";
import API_BASE from "@/lib/apiBase";

const TOWNS = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH", 
    "BUKIT PANJANG", "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG", 
    "CLEMENTI", "GEYLANG", "HOUGANG", "JURONG EAST", "JURONG WEST", 
    "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS", "PUNGGOL", 
    "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES", 
    "TOA PAYOH", "WOODLANDS", "YISHUN"
];

const FLAT_TYPES = ["2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI-GENERATION"];

export default function QuickPriceChecker() {
    const [town, setTown] = useState("TAMPINES");
    const [flatType, setFlatType] = useState("4 ROOM");
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<any>(null);

    const handleCheck = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/api/public/valuation-preview?town=${encodeURIComponent(town)}&flat_type=${encodeURIComponent(flatType)}`);
            if (res.ok) {
                const data = await res.json();
                setResult(data);
            }
        } catch (err) {
            console.error("Failed to check price", err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <section className="py-24 bg-slate-900 text-white overflow-hidden relative">
            <div className="absolute top-0 left-0 w-full h-full opacity-10 pointer-events-none">
                <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-accent rounded-full blur-[120px]" />
                <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary rounded-full blur-[120px]" />
            </div>

            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
                    <div>
                        <span className="text-accent font-bold uppercase tracking-widest text-xs">For Guests</span>
                        <h2 className="text-4xl font-extrabold tracking-tight mt-2 mb-6">
                            Instant Market <span className="text-accent">Benchmarks</span>
                        </h2>
                        <p className="text-slate-400 text-lg mb-8 leading-relaxed">
                            Not ready to sign up? Get a quick estimate based on real-time transaction averages in your town. 
                            Our database tracks every HDB resale since 2017 to give you the most accurate benchmarks.
                        </p>
                        
                        <div className="space-y-4">
                            <div className="flex items-start gap-4">
                                <div className="w-10 h-10 rounded-xl bg-accent/20 flex items-center justify-center flex-shrink-0">
                                    <Info className="w-5 h-5 text-accent" />
                                </div>
                                <p className="text-sm text-slate-400">
                                    Averages are calculated based on the last 12 months of HDB resale data.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 shadow-2xl">
                        <div className="space-y-6">
                            <div>
                                <label className="block text-xs font-bold uppercase text-slate-500 mb-2">Select Town</label>
                                <select 
                                    className="w-full bg-white/10 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none"
                                    value={town}
                                    onChange={(e) => setTown(e.target.value)}
                                >
                                    {TOWNS.map(t => <option key={t} value={t} className="bg-slate-800">{t}</option>)}
                                </select>
                            </div>

                            <div>
                                <label className="block text-xs font-bold uppercase text-slate-500 mb-2">Flat Type</label>
                                <select 
                                    className="w-full bg-white/10 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-accent/50 appearance-none"
                                    value={flatType}
                                    onChange={(e) => setFlatType(e.target.value)}
                                >
                                    {FLAT_TYPES.map(f => <option key={f} value={f} className="bg-slate-800">{f}</option>)}
                                </select>
                            </div>

                            <button 
                                onClick={handleCheck}
                                disabled={loading}
                                className="w-full bg-accent text-white font-bold py-4 rounded-xl hover:bg-accent/90 transition-all flex items-center justify-center gap-3 shadow-lg shadow-accent/20"
                            >
                                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Search className="w-5 h-5" />}
                                Get Instant Estimate
                            </button>
                        </div>

                        {result && (
                            <div className="mt-8 pt-8 border-t border-white/10 text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
                                <p className="text-xs font-bold uppercase text-slate-500 mb-2">Estimated Market Range</p>
                                <h3 className="text-3xl font-black text-white mb-2">
                                    {result.estimated_range}
                                </h3>
                                <p className="text-sm text-slate-400">
                                    Based on the average price of <span className="text-white font-bold">S${result.avg_price?.toLocaleString()}</span>
                                </p>
                                <button 
                                    onClick={() => window.location.href = '/register'}
                                    className="mt-6 text-sm font-bold text-accent hover:underline"
                                >
                                    Get precise AI valuation for your exact unit →
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </section>
    );
}
