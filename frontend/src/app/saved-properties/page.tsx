"use client";

import { useState, useEffect } from "react";
import Navbar from "@/components/Navbar";
import PropertyCard from "@/components/PropertyCard";
import { Search } from "lucide-react";
import RequireAuth from "@/components/RequireAuth";
import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

interface SavedProperty {
    id: number;
    property_name?: string;
    postal_code: string;
    property_type: string;
    floor_area?: number;
    lease_year?: number;
    estimated_price: number;
    created_at?: string;
}

export default function SavedPropertiesPage() {
    const [searchTerm, setSearchTerm] = useState("");
    const [properties, setProperties] = useState<SavedProperty[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const fetchProperties = async () => {
            const token = localStorage.getItem("token");
            if (!token) return;

            try {
                const res = await fetch(`${API_BASE}/api/user/saved-properties`, {
                    headers: subscriptionAwareHeaders(token),
                });
                if (res.ok) {
                    const data = await res.json();
                    setProperties(data);
                }
            } catch (err) {
                console.error("Failed to fetch saved properties", err);
            } finally {
                setIsLoading(false);
            }
        };

        fetchProperties();
    }, []);

    const handleDelete = async (id: number) => {
        const token = localStorage.getItem("token");
        if (!token) return;

        try {
            const res = await fetch(`${API_BASE}/api/user/saved-properties/${id}`, {
                method: "DELETE",
                headers: subscriptionAwareHeaders(token),
            });
            if (res.ok) {
                setProperties(prev => prev.filter(p => p.id !== id));
            } else {
                alert("Failed to delete property.");
            }
        } catch (err) {
            console.error("Failed to delete property", err);
            alert("Error deleting property.");
        }
    };

    const filtered = properties.filter(p =>
        (p.property_name && p.property_name.toLowerCase().includes(searchTerm.toLowerCase())) ||
        p.postal_code.includes(searchTerm)
    );

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 pb-20">
            <Navbar />

            <div className="max-w-7xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-end mb-10 gap-6">
                    <div>
                        <span className="text-accent font-bold uppercase tracking-widest text-xs">Your Portfolio</span>
                        <h1 className="text-4xl font-extrabold tracking-tight mt-2">Saved Properties</h1>
                    </div>

                    <div className="relative w-full md:w-72">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground/40" />
                        <input
                            type="text"
                            placeholder="Search saved properties..."
                            className="w-full bg-white/50 backdrop-blur-md border border-foreground/10 rounded-xl pl-10 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                    {isLoading ? (
                        <div className="col-span-full py-20 text-center text-foreground/40 font-medium">
                            Loading your saved properties...
                        </div>
                    ) : (
                        <>
                            {filtered.map(prop => (
                                <PropertyCard key={prop.id} property={prop as any} onDelete={handleDelete} />
                            ))}
                            {filtered.length === 0 && (
                                <div className="col-span-full py-20 text-center text-foreground/40 font-medium">
                                    No properties found matching your search.
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </main>
        </RequireAuth>
    )
}
