"use client";

import Link from "next/link";
import { useState, useRef, useEffect } from "react";
import {
    Home,
    CircleUser,
    LogOut,
    BarChart3,
    MessageSquare,
    ChevronDown,
    FileText,
    Bookmark,
    Wrench,
    BadgeDollarSign,
    Calculator,
    Briefcase,
    ShieldAlert,
    LogIn,
    UserPlus,
    LayoutDashboard,
    Database,
    HeartPulse,
    UserCog,
    Brain,
    ClipboardList,
    ScanEye,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import Logo from "@/components/Logo";

const navDropdownPanelClass =
    "absolute left-0 top-full mt-1 py-1 min-w-[12rem] rounded-lg border border-slate-200/80 bg-white/95 backdrop-blur-sm shadow-lg z-[1]";

const navAdminSectionClass =
    "px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-t border-slate-100 first:border-t-0 first:pt-1";

const navAdminLinkClass =
    "flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-red-50 hover:text-red-700 transition-colors";

export default function Navbar() {
    const { user, logout, adminPreviewSubscription, setAdminPreviewSubscription } = useAuth();
    const [toolsOpen, setToolsOpen] = useState(false);
    const [workspaceOpen, setWorkspaceOpen] = useState(false);
    const [adminOpen, setAdminOpen] = useState(false);
    const toolsRef = useRef<HTMLDivElement>(null);
    const workspaceRef = useRef<HTMLDivElement>(null);
    const adminRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        function handlePointerDown(e: PointerEvent) {
            const t = e.target as Node;
            if (toolsRef.current && !toolsRef.current.contains(t)) setToolsOpen(false);
            if (workspaceRef.current && !workspaceRef.current.contains(t)) setWorkspaceOpen(false);
            if (adminRef.current && !adminRef.current.contains(t)) setAdminOpen(false);
        }
        function handleKey(e: KeyboardEvent) {
            if (e.key === "Escape") {
                setToolsOpen(false);
                setWorkspaceOpen(false);
                setAdminOpen(false);
            }
        }
        document.addEventListener("pointerdown", handlePointerDown);
        document.addEventListener("keydown", handleKey);
        return () => {
            document.removeEventListener("pointerdown", handlePointerDown);
            document.removeEventListener("keydown", handleKey);
        };
    }, []);

    return (
        <nav className="fixed top-0 left-0 right-0 z-[10100] bg-white border-b border-slate-200 shadow-sm">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex justify-between items-center h-16">
                    <Logo size="sm" priority />

                    <div className="hidden md:flex items-center space-x-8">
                        <Link href="/" className="text-sm font-medium hover:text-accent transition-colors inline-flex items-center gap-1.5">
                            <Home className="w-3.5 h-3.5 shrink-0 opacity-80" />
                            Home
                        </Link>
                        <div className="relative" ref={toolsRef}>
                            <button
                                type="button"
                                className="text-sm font-medium hover:text-accent transition-colors inline-flex items-center gap-1.5"
                                aria-expanded={toolsOpen}
                                aria-haspopup="true"
                                aria-controls="nav-tools-menu"
                                id="nav-tools-trigger"
                                onClick={() => {
                                    setWorkspaceOpen(false);
                                    setAdminOpen(false);
                                    setToolsOpen((o) => !o);
                                }}
                            >
                                <Wrench className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                Tools
                                <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${toolsOpen ? "rotate-180" : ""}`} />
                            </button>
                            {toolsOpen && (
                                <div
                                    id="nav-tools-menu"
                                    role="menu"
                                    aria-labelledby="nav-tools-trigger"
                                    className={navDropdownPanelClass}
                                >
                                    <Link
                                        href="/valuation"
                                        role="menuitem"
                                        className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-accent transition-colors"
                                        onClick={() => setToolsOpen(false)}
                                    >
                                        <BadgeDollarSign className="w-3.5 h-3.5 shrink-0" />
                                        Valuation
                                    </Link>
                                    <Link
                                        href="/calculators"
                                        role="menuitem"
                                        className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-accent transition-colors"
                                        onClick={() => setToolsOpen(false)}
                                    >
                                        <Calculator className="w-3.5 h-3.5 shrink-0" />
                                        Calculators
                                    </Link>
                                    {user && (
                                        <Link
                                            href="/chat"
                                            role="menuitem"
                                            className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-accent transition-colors"
                                            onClick={() => setToolsOpen(false)}
                                        >
                                            <MessageSquare className="w-3.5 h-3.5 shrink-0" />
                                            AI Chat
                                        </Link>
                                    )}
                                </div>
                            )}
                        </div>
                        <Link href="/analytics" className="text-sm font-medium hover:text-accent transition-colors inline-flex items-center gap-1.5">
                            <BarChart3 className="w-3.5 h-3.5 shrink-0 opacity-80" />
                            Analytics
                        </Link>
                        {user && (
                            <>
                                <div className="relative" ref={workspaceRef}>
                                    <button
                                        type="button"
                                        className="text-sm font-medium hover:text-accent transition-colors inline-flex items-center gap-1.5"
                                        aria-expanded={workspaceOpen}
                                        aria-haspopup="true"
                                        aria-controls="nav-workspace-menu"
                                        id="nav-workspace-trigger"
                                        onClick={() => {
                                            setToolsOpen(false);
                                            setAdminOpen(false);
                                            setWorkspaceOpen((o) => !o);
                                        }}
                                    >
                                        <Briefcase className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                        Workspace
                                        <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${workspaceOpen ? "rotate-180" : ""}`} />
                                    </button>
                                    {workspaceOpen && (
                                        <div
                                            id="nav-workspace-menu"
                                            role="menu"
                                            aria-labelledby="nav-workspace-trigger"
                                            className={navDropdownPanelClass}
                                        >
                                            <Link
                                                href="/reports"
                                                role="menuitem"
                                                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-accent transition-colors"
                                                onClick={() => setWorkspaceOpen(false)}
                                            >
                                                <FileText className="w-3.5 h-3.5 shrink-0" />
                                                Reports
                                            </Link>
                                            <Link
                                                href="/saved-properties"
                                                role="menuitem"
                                                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 hover:text-accent transition-colors"
                                                onClick={() => setWorkspaceOpen(false)}
                                            >
                                                <Bookmark className="w-3.5 h-3.5 shrink-0" />
                                                Saved properties
                                            </Link>
                                        </div>
                                    )}
                                </div>
                                {user.role === "admin" && (
                                    <div className="relative" ref={adminRef}>
                                        <button
                                            type="button"
                                            className="text-sm font-medium text-red-600 hover:text-red-700 transition-colors inline-flex items-center gap-1.5"
                                            aria-expanded={adminOpen}
                                            aria-haspopup="true"
                                            aria-controls="nav-admin-menu"
                                            id="nav-admin-trigger"
                                            onClick={() => {
                                                setToolsOpen(false);
                                                setWorkspaceOpen(false);
                                                setAdminOpen((o) => !o);
                                            }}
                                        >
                                            <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
                                            Admin
                                            <ChevronDown className={`w-3.5 h-3.5 shrink-0 transition-transform ${adminOpen ? "rotate-180" : ""}`} />
                                        </button>
                                        {adminOpen && (
                                            <div
                                                id="nav-admin-menu"
                                                role="menu"
                                                aria-labelledby="nav-admin-trigger"
                                                className={`${navDropdownPanelClass} min-w-[15.5rem] py-2 border-red-200/60`}
                                            >
                                                <div className={navAdminSectionClass} role="presentation">
                                                    Overview
                                                </div>
                                                <Link
                                                    href="/admin"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <LayoutDashboard className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    Admin dashboard
                                                </Link>

                                                <div className={navAdminSectionClass} role="presentation">
                                                    Data &amp; assets
                                                </div>
                                                <Link
                                                    href="/admin/data-catalog"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <Database className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    Data catalog
                                                </Link>
                                                <Link
                                                    href="/admin/data-completeness"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <ClipboardList className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    Data completeness
                                                </Link>

                                                <div className={navAdminSectionClass} role="presentation">
                                                    Machine learning
                                                </div>
                                                <Link
                                                    href="/admin/models"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <Brain className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    Model management
                                                </Link>

                                                <div className={navAdminSectionClass} role="presentation">
                                                    Reliability
                                                </div>
                                                <Link
                                                    href="/admin/health"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <HeartPulse className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    System health
                                                </Link>

                                                <div className={navAdminSectionClass} role="presentation">
                                                    Access &amp; users
                                                </div>
                                                <Link
                                                    href="/admin/users"
                                                    role="menuitem"
                                                    className={navAdminLinkClass}
                                                    onClick={() => setAdminOpen(false)}
                                                >
                                                    <UserCog className="w-3.5 h-3.5 shrink-0 opacity-80" />
                                                    User management
                                                </Link>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    <div className="flex items-center gap-2 sm:gap-3 shrink-0">
                        {user?.role === "admin" && (
                            <div
                                className="hidden lg:flex items-center gap-1.5 rounded-lg border border-violet-200 bg-violet-50/80 px-1.5 py-1"
                                title="Preview subscriber experience. Does not change database roles."
                            >
                                <ScanEye className="w-3.5 h-3.5 text-violet-700 shrink-0" aria-hidden />
                                <span className="text-[10px] font-bold uppercase tracking-wide text-violet-800 whitespace-nowrap">
                                    View as
                                </span>
                                <div className="flex rounded-md border border-violet-200/80 bg-white/90 p-0.5 gap-0.5">
                                    {(["off", "free", "premium"] as const).map((mode) => {
                                        const active =
                                            mode === "off"
                                                ? adminPreviewSubscription === null
                                                : adminPreviewSubscription === mode;
                                        return (
                                            <button
                                                key={mode}
                                                type="button"
                                                onClick={() =>
                                                    setAdminPreviewSubscription(mode === "off" ? null : mode)
                                                }
                                                className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded transition-colors ${
                                                    active
                                                        ? "bg-violet-600 text-white shadow-sm"
                                                        : "text-violet-900/70 hover:bg-violet-100"
                                                }`}
                                            >
                                                {mode === "off" ? "Off" : mode}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                        {user ? (
                            <div className="flex items-center gap-2 sm:gap-3">
                                <Link
                                    href="/profile"
                                    className="p-2 rounded-full hover:bg-slate-100 text-slate-600 hover:text-accent transition-colors"
                                    aria-label="Profile"
                                    title="Profile"
                                >
                                    <CircleUser className="w-5 h-5" />
                                </Link>
                                <div className="hidden sm:flex flex-col items-end">
                                    <span className="text-sm font-semibold">{user.full_name}</span>
                                    <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{user.role}</span>
                                </div>
                                <button
                                    type="button"
                                    onClick={logout}
                                    className="p-2 rounded-full hover:bg-slate-100 text-slate-500 hover:text-red-500 transition-colors"
                                    title="Logout"
                                >
                                    <LogOut className="w-5 h-5" />
                                </button>
                            </div>
                        ) : (
                            <>
                                <Link
                                    href="/login"
                                    className="hidden sm:inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium h-9 px-4 py-2 hover:bg-black/5 transition-colors"
                                >
                                    <LogIn className="w-3.5 h-3.5 shrink-0 opacity-70" />
                                    Login
                                </Link>
                                <Link
                                    href="/register"
                                    className="inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium h-9 px-4 py-2 bg-accent text-white hover:bg-accent/90 shadow-md hover:shadow-lg transition-all"
                                >
                                    <UserPlus className="w-3.5 h-3.5 shrink-0" />
                                    Sign Up
                                </Link>
                            </>
                        )}
                    </div>
                </div>
            </div>
        </nav>
    );
}
