"use client";

import { useState, useEffect, useRef, Suspense } from "react";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
    FileText,
    Download,
    Check,
    AlertCircle,
    Building2,
    TrendingUp,
    MapPin,
    BookOpen,
    Eye,
    Loader2
} from "lucide-react";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

interface ReportConfig {
    include_property_details: boolean;
    include_valuation_summary: boolean;
    include_amenities: boolean;
    include_market_insights: boolean;
    include_market_sentiment: boolean;
    include_comparative_analysis: boolean;
}

interface PropertyData {
    postal_code: string;
    town: string;
    flat_type: string;
    flat_model_grouped: string;
    region: string;
    storey_midpoint: number;
    floor_area_sqm: number;
    remaining_lease_years: number;
}

interface ValuationData {
    predicted_price: number;
    confidence_interval: number[];
    confidence_interval_method?: string;
    interval_coverage?: number;
    interval_calibration?: Record<string, unknown>;
    amenities: {
        mrt: string;
        school: string;
        cbd_distance: string;
    };
    shap_values?: Record<string, unknown> | { feature: string; contribution: number }[];
}

export default function ValuationReportPage() {
    return (
        <Suspense fallback={
            <div className="min-h-screen bg-slate-50 flex items-center justify-center">
                <Navbar />
                <div className="text-center p-8">
                    <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-lg font-semibold">Loading...</p>
                </div>
            </div>
        }>
            <ValuationReportContent />
        </Suspense>
    );
}

function ValuationReportContent() {
    const { user, isLoading, isPremiumExperience } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();
    const [loading, setLoading] = useState(false);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [config, setConfig] = useState<ReportConfig>({
        include_property_details: true,
        include_valuation_summary: true,
        include_amenities: true,
        include_market_insights: true,
        include_market_sentiment: true,
        include_comparative_analysis: true
    });
    const [propertyData, setPropertyData] = useState<PropertyData | null>(null);
    const [valuationData, setValuationData] = useState<ValuationData | null>(null);
    const [accessError, setAccessError] = useState<string | null>(null);
    const [htmlPreview, setHtmlPreview] = useState<string>('');
    const [pageCount, setPageCount] = useState(1);
    const iframeRef = useRef<HTMLIFrameElement>(null);

    useEffect(() => {
        // Wait for auth to finish loading
        if (isLoading) {
            return;
        }

        // Check if user is logged in
        if (!user) {
            setAccessError('Please login to access this page. Redirecting to login...');
            setTimeout(() => router.push('/login'), 2000);
            return;
        }

        // Check if user is premium
        if (!isPremiumExperience) {
            setAccessError('PDF reports are only available for Premium subscribers. Redirecting...');
            setTimeout(() => router.push('/valuation'), 2500);
            return;
        }

        // Get data from URL params or localStorage
        const storedProperty = localStorage.getItem('lastValuationProperty');
        const storedValuation = localStorage.getItem('lastValuationResult');

        console.log('Stored property:', storedProperty);
        console.log('Stored valuation:', storedValuation);

        if (!storedProperty) {
            setAccessError('No valuation data found. Please complete a valuation first. Redirecting...');
            setTimeout(() => router.push('/valuation'), 2500);
            return;
        }

        const parsedProperty = JSON.parse(storedProperty) as PropertyData & {
            remaining_lease?: number;
        };
        if (
            parsedProperty.remaining_lease_years == null &&
            parsedProperty.remaining_lease != null
        ) {
            parsedProperty.remaining_lease_years = parsedProperty.remaining_lease;
        }
        setPropertyData(parsedProperty);

        if (!storedValuation) {
            setAccessError('No valuation result found. Please complete a valuation first. Redirecting...');
            setTimeout(() => router.push('/valuation'), 2500);
            return;
        }

        setValuationData(JSON.parse(storedValuation));
    }, [user, isLoading, router, isPremiumExperience]);

    // Fetch HTML preview when data or config changes
    useEffect(() => {
        if (propertyData && valuationData && isPremiumExperience) {
            fetchHtmlPreview();
        }
    }, [propertyData, valuationData, config, isPremiumExperience]);

    const fetchHtmlPreview = async () => {
        if (!propertyData || !valuationData) {
            return;
        }
        setPreviewLoading(true);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`${API_BASE}/api/reports/valuation/preview/html`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    property_data: {
                        postal_code: propertyData.postal_code,
                        town: propertyData.town,
                        flat_type: propertyData.flat_type,
                        flat_model_grouped: propertyData.flat_model_grouped,
                        region: propertyData.region,
                        storey_midpoint: propertyData.storey_midpoint,
                        floor_area_sqm: propertyData.floor_area_sqm,
                        remaining_lease_years: propertyData.remaining_lease_years
                    },
                    valuation_data: valuationData,
                    report_config: config
                })
            });

            if (response.ok) {
                const data = await response.json();
                setHtmlPreview(data.html);
                setPageCount(data.page_count);
            }
        } catch (error) {
            console.error('Preview generation failed:', error);
        } finally {
            setPreviewLoading(false);
        }
    };

    // Show loading spinner while auth is loading or data is being fetched
    if (isLoading || !propertyData || !valuationData) {
        return (
            <main className="min-h-screen bg-slate-50 flex items-center justify-center">
                <Navbar />
                <div className="text-center p-8">
                    <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-lg font-semibold">{accessError || (isLoading ? 'Loading your session...' : 'Loading valuation data...')}</p>
                </div>
            </main>
        );
    }

    // Show error if user is not premium (after auth loaded)
    if (!user || !isPremiumExperience) {
        return (
            <main className="min-h-screen bg-slate-50 flex items-center justify-center">
                <Navbar />
                <div className="text-center p-8">
                    <div className="w-12 h-12 border-4 border-red-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-lg font-semibold text-red-500">PDF reports are only available for Premium subscribers.</p>
                    <p className="text-sm text-foreground/50 mt-2">Redirecting to valuation page...</p>
                </div>
            </main>
        );
    }

    const toggleMetric = (key: keyof ReportConfig) => {
        setConfig(prev => ({
            ...prev,
            [key]: !prev[key]
        }));
        // Preview will auto-update via useEffect
    };

    const handleDownloadPDF = async () => {
        setLoading(true);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`${API_BASE}/api/reports/valuation/pdf`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    property_data: {
                        postal_code: propertyData.postal_code,
                        town: propertyData.town,
                        flat_type: propertyData.flat_type,
                        flat_model_grouped: propertyData.flat_model_grouped,
                        region: propertyData.region,
                        storey_midpoint: propertyData.storey_midpoint,
                        floor_area_sqm: propertyData.floor_area_sqm,
                        remaining_lease_years: propertyData.remaining_lease_years
                    },
                    valuation_data: valuationData,
                    report_config: config
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to generate report');
            }

            // Download the PDF
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `homeyai_valuation_report_${propertyData.postal_code}.pdf`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(url);
        } catch (error) {
            console.error('PDF generation failed:', error);
            alert('Failed to generate PDF report. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    const selectedCount = Object.values(config).filter(Boolean).length;

    return (
        <main className="min-h-screen bg-slate-50">
            <Navbar />

            <div className="max-w-7xl mx-auto pt-32 pb-20 px-4">
                <div className="mb-12">
                    <h1 className="text-4xl font-extrabold mb-4 tracking-tight flex items-center gap-3">
                        <FileText className="w-10 h-10 text-accent" />
                        Valuation Report
                    </h1>
                    <p className="text-foreground/50 text-lg">
                        Customize and download your professional property valuation report
                    </p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                    {/* Left: Live HTML Preview with iframe */}
                    <div className="lg:col-span-3 space-y-6">
                        <div className="glass rounded-3xl p-6 shadow-xl">
                            <div className="flex items-center justify-between mb-6">
                                <h2 className="text-xl font-bold flex items-center gap-2">
                                    <Eye className="w-5 h-5 text-accent" />
                                    Live Preview
                                </h2>
                                <AnimatePresence mode="wait">
                                    {previewLoading ? (
                                        <motion.div
                                            key="loading"
                                            initial={{ opacity: 0 }}
                                            animate={{ opacity: 1 }}
                                            exit={{ opacity: 0 }}
                                            className="flex items-center gap-2 text-sm text-accent"
                                        >
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            Updating...
                                        </motion.div>
                                    ) : (
                                        <motion.div
                                            key="pages"
                                            initial={{ opacity: 0, scale: 0.8 }}
                                            animate={{ opacity: 1, scale: 1 }}
                                            exit={{ opacity: 0, scale: 0.8 }}
                                            className="flex items-center gap-2 px-4 py-2 bg-accent/10 rounded-full"
                                        >
                                            <FileText className="w-4 h-4 text-accent" />
                                            <span className="font-bold text-accent">{pageCount} preview section{pageCount > 1 ? 's' : ''}; PDF pagination may differ</span>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>

                            {/* HTML Preview in scrollable container */}
                            <div className="relative border rounded-xl overflow-hidden bg-slate-100">
                                {previewLoading && (
                                    <div className="absolute inset-0 bg-white/80 backdrop-blur-sm z-10 flex items-center justify-center">
                                        <div className="text-center">
                                            <Loader2 className="w-8 h-8 animate-spin mx-auto text-accent mb-2" />
                                            <p className="text-sm text-accent font-medium">Generating preview...</p>
                                        </div>
                                    </div>
                                )}
                                <div className="overflow-auto max-h-[700px]">
                                    {htmlPreview ? (
                                        <iframe
                                            ref={iframeRef}
                                            srcDoc={htmlPreview}
                                            className="w-full"
                                            style={{ height: '700px', border: 'none' }}
                                            title="Report Preview"
                                            sandbox="allow-scripts"
                                        />
                                    ) : (
                                        <div className="h-[700px] flex items-center justify-center text-foreground/50">
                                            <p>Loading preview...</p>
                                        </div>
                                    )}
                                </div>
                            </div>

                            <p className="text-xs text-foreground/40 mt-4 text-center">
                                This is a live preview. The actual PDF may have slight variations.
                            </p>
                        </div>
                    </div>

                    {/* Right: Metrics Toggle Panel */}
                    <div className="space-y-6">
                        <div className="glass rounded-3xl p-6 shadow-xl sticky top-24">
                            <h2 className="text-xl font-bold mb-4">Customize Report</h2>
                            <p className="text-sm text-foreground/50 mb-6">
                                Select which sections to include in your PDF report
                            </p>

                            <div className="space-y-3 mb-6">
                                <ToggleItem
                                    icon={<Building2 className="w-5 h-5" />}
                                    label="Property Details"
                                    description="Specifications & features"
                                    checked={config.include_property_details}
                                    onChange={() => toggleMetric('include_property_details')}
                                />

                                <ToggleItem
                                    icon={<TrendingUp className="w-5 h-5" />}
                                    label="Valuation Summary"
                                    description="Price & confidence interval"
                                    checked={config.include_valuation_summary}
                                    onChange={() => toggleMetric('include_valuation_summary')}
                                />

                                <ToggleItem
                                    icon={<MapPin className="w-5 h-5" />}
                                    label="Nearby Amenities"
                                    description="MRT, schools, CBD distance"
                                    checked={config.include_amenities}
                                    onChange={() => toggleMetric('include_amenities')}
                                />

                                <ToggleItem
                                    icon={<BookOpen className="w-5 h-5" />}
                                    label="Market Insights"
                                    description="Analysis & context"
                                    checked={config.include_market_insights}
                                    onChange={() => toggleMetric('include_market_insights')}
                                />

                                <ToggleItem
                                    icon={<TrendingUp className="w-5 h-5" />}
                                    label="Market Intelligence"
                                    description="Macro sentiment & rates"
                                    checked={config.include_market_sentiment}
                                    onChange={() => toggleMetric('include_market_sentiment')}
                                />

                                <ToggleItem
                                    icon={<TrendingUp className="w-5 h-5" />}
                                    label="Comparative Analysis"
                                    description="Neighbor transactions"
                                    checked={config.include_comparative_analysis}
                                    onChange={() => toggleMetric('include_comparative_analysis')}
                                />
                            </div>

                            <div className="border-t border-foreground/10 pt-4 mb-6">
                                <div className="flex justify-between text-sm mb-2">
                                    <span className="text-foreground/50">Selected sections</span>
                                    <span className="font-bold">{selectedCount} of 6</span>
                                </div>
                                <div className="w-full bg-foreground/10 rounded-full h-2">
                                    <div
                                        className="bg-accent h-2 rounded-full transition-all duration-300"
                                        style={{ width: `${(selectedCount / 6) * 100}%` }}
                                    />
                                </div>
                            </div>

                            {selectedCount === 0 && (
                                <div className="bg-orange-500/10 border border-orange-500/20 rounded-xl p-4 flex items-start gap-3 mb-4">
                                    <AlertCircle className="w-5 h-5 text-orange-500 flex-shrink-0 mt-0.5" />
                                    <p className="text-sm text-orange-500">
                                        Please select at least one section to include in your report
                                    </p>
                                </div>
                            )}

                            <button
                                onClick={handleDownloadPDF}
                                disabled={loading || selectedCount === 0}
                                className="w-full bg-accent text-white py-4 rounded-xl font-bold hover:shadow-lg hover:shadow-accent/25 transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none mb-6"
                            >
                                {loading ? (
                                    <>
                                        <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                        Generating PDF...
                                    </>
                                ) : (
                                    <>
                                        <Download className="w-5 h-5" />
                                        Download PDF Report
                                    </>
                                )}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    );
}

function ToggleItem({
    icon,
    label,
    description,
    checked,
    onChange
}: {
    icon: React.ReactNode,
    label: string,
    description: string,
    checked: boolean,
    onChange: () => void
}) {
    return (
        <label className="flex items-center gap-3 p-3 rounded-xl border border-foreground/10 cursor-pointer hover:bg-foreground/5 transition-colors">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${checked ? 'bg-accent text-white' : 'bg-foreground/10 text-foreground/40'}`}>
                {icon}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{label}</span>
                    {checked && <Check className="w-3.5 h-3.5 text-accent" />}
                </div>
                <p className="text-xs text-foreground/50">{description}</p>
            </div>
            <input
                type="checkbox"
                checked={checked}
                onChange={onChange}
                className="w-5 h-5 rounded border-foreground/20 text-accent focus:ring-accent focus:ring-offset-0"
            />
        </label>
    );
}
