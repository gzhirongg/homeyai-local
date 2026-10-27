"use client";

import Navbar from "@/components/Navbar";
import { User, Shield, CreditCard, LogOut, Download } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import RequireAuth from "@/components/RequireAuth";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

export default function ProfilePage() {
    const { user, logout, deleteAccount, updateProfile, refreshProfile, isLoading } = useAuth();
    const [fullName, setFullName] = useState("");
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");

    useEffect(() => {
        if (user) setFullName(user.full_name || "");
    }, [user]);

    useEffect(() => {
        // Refresh once when the profile page loads (avoid re-running on every render)
        if (user) refreshProfile().catch(() => {});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user?.email]);

    const canSave = useMemo(() => {
        if (!user) return false;
        const nextName = fullName.trim();
        return nextName.length > 0 && nextName !== (user.full_name || "");
    }, [fullName, user]);

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />
            
            <div className="max-w-4xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                <h1 className="text-4xl font-extrabold tracking-tight mb-10">Account Settings</h1>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                    {/* Sidebar */}
                    <div className="space-y-2">
                        <button className="w-full flex items-center gap-3 px-4 py-3 bg-white rounded-xl font-bold text-accent shadow-sm border border-foreground/5">
                            <User className="w-5 h-5" /> Profile
                        </button>
                        <button className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white rounded-xl font-medium text-foreground/70 transition-colors">
                            <CreditCard className="w-5 h-5" /> Billing & Security
                        </button>
                        <button onClick={logout} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-red-50 rounded-xl font-medium text-red-500 transition-colors mt-8">
                            <LogOut className="w-5 h-5" /> Sign Out
                        </button>
                    </div>

                    {/* Main Content */}
                    <div className="md:col-span-2 space-y-8">
                        {/* Profile Info */}
                        <div className="glass rounded-3xl p-8 shadow-sm border border-foreground/5">
                            <h2 className="text-xl font-bold mb-6">Personal Information</h2>
                            <div className="space-y-4">
                                {error && (
                                    <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm border border-red-100">
                                        {error}
                                    </div>
                                )}
                                {success && (
                                    <div className="bg-emerald-50 text-emerald-700 p-3 rounded-lg text-sm border border-emerald-100">
                                        {success}
                                    </div>
                                )}
                                <div>
                                    <label className="block text-sm font-medium mb-2 text-foreground/70">Full Name</label>
                                    <input 
                                        type="text" 
                                        value={fullName}
                                        onChange={(e) => {
                                            setFullName(e.target.value);
                                            setError("");
                                            setSuccess("");
                                        }}
                                        className="w-full bg-background border border-foreground/10 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-accent"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium mb-2 text-foreground/70">Email Address</label>
                                    <input 
                                        type="email" 
                                        defaultValue={user?.email ?? ""}
                                        disabled
                                        className="w-full bg-foreground/5 border border-foreground/10 rounded-xl px-4 py-3 outline-none text-foreground/50 cursor-not-allowed"
                                    />
                                </div>
                                <button
                                    disabled={!canSave || isSaving}
                                    onClick={async () => {
                                        setIsSaving(true);
                                        setError("");
                                        setSuccess("");
                                        try {
                                            await updateProfile(fullName.trim());
                                            setSuccess("Profile updated successfully.");
                                        } catch (e: any) {
                                            setError(e?.message || "Failed to update profile");
                                        } finally {
                                            setIsSaving(false);
                                        }
                                    }}
                                    className="bg-foreground disabled:opacity-50 disabled:cursor-not-allowed text-background px-6 py-2.5 rounded-xl font-bold hover:shadow-lg transition-all mt-4"
                                >
                                    Save Changes
                                </button>
                            </div>
                        </div>

                        {/* Subscription Info */}
                        <div className="glass rounded-3xl p-8 shadow-sm border border-foreground/5 relative overflow-hidden">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-accent/5 rounded-full -mr-16 -mt-16 blur-xl" />
                            <h2 className="text-xl font-bold mb-6">Subscription Plan</h2>
                            
                            <div className="p-6 rounded-2xl border-2 border-accent bg-accent/5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                                <div>
                                    <span className="inline-block px-2 py-1 bg-accent/20 text-accent text-xs font-bold uppercase rounded-md mb-2">Current Plan</span>
                                    <h3 className="text-2xl font-black capitalize">{user?.role ?? ""} Tier</h3>
                                    {user?.role === 'free' && (
                                        <p className="text-sm font-medium text-foreground/60 mt-1">{user?.remaining_valuations ?? 3}/3 Free Valuations Remaining</p>
                                    )}
                                </div>
                                {user?.role === 'free' ? (
                                    <Link
                                        href="/#pricing"
                                        className="inline-flex items-center justify-center bg-accent text-white px-6 py-3 rounded-xl font-bold hover:shadow-lg hover:-translate-y-0.5 transition-all"
                                    >
                                        View plans & pricing
                                    </Link>
                                ) : (
                                    <button className="border border-foreground/20 px-6 py-3 rounded-xl font-bold hover:bg-black/5 transition-all">
                                        Manage Billing
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* Danger Zone */}
                        <div className="glass rounded-3xl p-8 shadow-sm border border-red-500/20">
                            <h2 className="text-xl font-bold mb-2 text-red-500">Danger Zone</h2>
                            <p className="text-sm text-foreground/60 mb-6">Once you delete your account, there is no going back. Please be certain.</p>
                            <button 
                                onClick={async () => {
                                    if (window.confirm("Are you absolutely sure you want to delete your account? This action cannot be undone.")) {
                                        try {
                                            await deleteAccount();
                                        } catch (e: any) {
                                            alert(e.message || "Failed to delete account");
                                        }
                                    }
                                }}
                                className="border border-red-500/50 text-red-500 px-6 py-2.5 rounded-xl font-bold hover:bg-red-500/10 transition-all"
                            >
                                Delete Account
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            </main>
        </RequireAuth>
    )
}
