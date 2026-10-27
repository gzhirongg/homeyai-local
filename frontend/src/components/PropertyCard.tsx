import { MapPin, Expand, Calendar, Trash2 } from "lucide-react";
import Link from "next/link";
import React from "react";

interface PropertyCardProps {
    property: any;
    onDelete?: (id: number) => void;
}

const PropertyCard: React.FC<PropertyCardProps> = ({ property, onDelete }) => {
    return (
        <div className="glass rounded-xl p-4 shadow-sm border-foreground/5 hover:shadow-lg transition-shadow bg-white border border-transparent hover:border-accent/20 group relative">
            {onDelete && (
                <button 
                    onClick={(e) => {
                        e.preventDefault();
                        if (window.confirm("Are you sure you want to delete this saved property?")) {
                            onDelete(property.id);
                        }
                    }}
                    className="absolute top-4 right-4 text-foreground/20 hover:text-red-500 transition-colors z-10"
                >
                    <Trash2 className="w-4 h-4" />
                </button>
            )}
            <h4 className="font-bold text-lg group-hover:text-accent transition-colors truncate pr-8">{property.property_name || property.postal_code}</h4>
            <div className="flex items-center gap-1 text-xs text-foreground/50 mt-1 mb-3">
                <MapPin className="w-3 h-3" />
                <span>{property.postal_code}</span>
            </div>
            
            <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="bg-secondary/5 rounded-md p-2 flex items-center gap-2">
                    <Expand className="w-3 h-3 text-secondary" />
                    <div>
                        <p className="text-[10px] uppercase text-foreground/40 font-bold">Type</p>
                        <p className="text-xs font-semibold">{property.property_type || "N/A"}</p>
                    </div>
                </div>
                <div className="bg-accent/5 rounded-md p-2 flex items-center gap-2">
                    <Calendar className="w-3 h-3 text-accent" />
                    <div>
                        <p className="text-[10px] uppercase text-foreground/40 font-bold">Date Saved</p>
                        <p className="text-xs font-semibold">
                            {property.created_at ? new Date(property.created_at).toLocaleDateString() : "N/A"}
                        </p>
                    </div>
                </div>
            </div>

            <div className="flex items-end justify-between border-t border-foreground/5 pt-3">
                <div>
                    <p className="text-[10px] uppercase text-foreground/40 font-bold">Est. Value</p>
                    <p className="text-lg font-black text-gradient">S${property.predicted_price?.toLocaleString() || "---"}</p>
                </div>
                <Link href={`/valuation-report?id=${property.id}`} className="text-xs font-bold text-accent bg-accent/10 px-3 py-1.5 rounded-md hover:bg-accent/20 transition-colors">
                    Report
                </Link>
            </div>
        </div>
    );
};

export default PropertyCard;
