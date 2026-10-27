"use client";

import { Calendar, MapPin, Trash2, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";

type SavedProperty = {
  id: number;
  postal_code: string;
  property_type: string;
  predicted_price: number;
  created_at?: string;
};

export default function SavedPropertyCard({
  property,
  onDelete,
}: {
  property: SavedProperty;
  onDelete: (id: number) => void;
}) {
  const router = useRouter();
  const { user, isPremiumExperience: isPremium } = useAuth();
  const dateLabel = property.created_at ? new Date(property.created_at).toLocaleString() : "—";

  const handleViewReport = () => {
    // Store property data for report generation
    localStorage.setItem('lastValuationProperty', JSON.stringify({
      postal_code: property.postal_code,
      property_type: property.property_type,
      floor_area: 100, // Default values for saved properties
      lease_year: 2000,
      floor_level: "04 to 06"
    }));
    localStorage.setItem('lastValuationResult', JSON.stringify({
      predicted_price: property.predicted_price,
      confidence_interval: [property.predicted_price * 0.9, property.predicted_price * 1.1],
      amenities: { mrt: "N/A", school: "N/A", cbd_distance: "N/A" }
    }));
    router.push('/valuation-report');
  };

  return (
    <div className="glass rounded-xl p-4 shadow-sm border-foreground/5 hover:shadow-lg transition-shadow bg-white border border-transparent hover:border-accent/20">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 className="font-bold text-lg truncate">
            {property.property_type} • {property.postal_code}
          </h4>
          <div className="flex items-center gap-3 text-xs text-foreground/50 mt-2">
            <span className="inline-flex items-center gap-1">
              <MapPin className="w-3 h-3" />
              {property.postal_code}
            </span>
            <span className="inline-flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {dateLabel}
            </span>
          </div>
        </div>

        <button
          onClick={() => onDelete(property.id)}
          className="p-2 rounded-lg hover:bg-red-500/10 text-foreground/50 hover:text-red-600 transition-colors"
          title="Delete saved property"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="flex items-end justify-between border-t border-foreground/5 pt-3 mt-4">
        <div>
          <p className="text-[10px] uppercase text-foreground/40 font-bold">Saved valuation</p>
          <p className="text-lg font-black text-gradient">
            S${Number(property.predicted_price || 0).toLocaleString()}
          </p>
        </div>
        {isPremium && (
          <button
            onClick={handleViewReport}
            className="flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:shadow-lg transition-all text-sm font-bold"
          >
            <FileText className="w-4 h-4" />
            View Report
          </button>
        )}
      </div>
      {!isPremium && (
        <div className="mt-3 pt-3 border-t border-foreground/5">
          <p className="text-xs text-orange-500 text-center">
            Upgrade to Premium to download PDF reports
          </p>
        </div>
      )}
    </div>
  );
}

