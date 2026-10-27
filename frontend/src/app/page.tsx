"use client";

import Navbar from "@/components/Navbar";
import Hero from "@/components/Hero";
import { LayoutDashboard, TrendingUp, Search, FileText, CheckCircle2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const MARKETING_VIDEO_SRC = "/videos/HomeyAI_MarketingVideo.mp4";

export default function Home() {
  const [isPlaying, setIsPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (isPlaying) {
      void videoRef.current?.play();
    }
  }, [isPlaying]);

  return (
    <main className="min-h-screen bg-slate-50">
      <Navbar />
      <Hero />

      {/* Featured Sections / Brief Highlights */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 border-t border-foreground/5">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 text-center">
          <FeatureCard
            icon={<Search className="w-6 h-6" />}
            title="Instant Search"
            description="Get quick estimates by just typing a postal code."
          />
          <FeatureCard
            icon={<LayoutDashboard className="w-6 h-6" />}
            title="Interactive Dashboard"
            description="Deep dive into neighborhood amenities and trends."
          />
          <FeatureCard
            icon={<TrendingUp className="w-6 h-6" />}
            title="XAI Analysis"
            description="Understand why our model predicts that specific price."
          />
          <FeatureCard
            icon={<FileText className="w-6 h-6" />}
            title="Valuation Reports"
            description="Premium subscribers can generate professional PDFs."
          />
        </div>
      </section>
      
      {/* Demo Video Section */}
      <section className="bg-white py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl font-bold mb-4">See HomeyAI in Action</h2>
          <p className="text-slate-500 max-w-2xl mx-auto mb-12">
            Discover how easy it is to get professional real estate valuations and deep market insights with our AI-powered platform.
          </p>
          
          <div className="relative aspect-video max-w-4xl mx-auto rounded-3xl overflow-hidden shadow-2xl border-8 border-slate-50 group bg-slate-900">
            <video
              ref={videoRef}
              src={MARKETING_VIDEO_SRC}
              title="HomeyAI marketing video"
              className="w-full h-full object-cover"
              preload={isPlaying ? "auto" : "metadata"}
              controls={isPlaying}
              muted={!isPlaying}
              playsInline
            />
            {!isPlaying && (
              <button
                type="button"
                aria-label="Play marketing video"
                className="absolute inset-0 bg-black/20 group-hover:bg-black/10 transition-colors flex items-center justify-center z-10 cursor-pointer"
                onClick={() => setIsPlaying(true)}
              >
                <span className="w-20 h-20 bg-accent text-white rounded-full flex items-center justify-center shadow-2xl group-hover:scale-110 transition-transform">
                  <svg className="w-8 h-8 fill-current translate-x-1" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </span>
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Pricing Section — linked from upgrade CTAs (e.g. Analytics) as /#pricing */}
      <section id="pricing" className="py-24 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 scroll-mt-24">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-bold mb-4">Simple, Transparent Pricing</h2>
          <p className="text-foreground/60 max-w-2xl mx-auto">
            Choose the perfect plan for your real estate valuation needs. 
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
          {/* Free Tier */}
          <div className="glass rounded-3xl p-8 shadow-sm border border-foreground/5 hover:border-accent/20 transition-colors flex flex-col">
            <h3 className="text-xl font-bold mb-2">Free User</h3>
            <div className="text-4xl font-extrabold mb-6">$0<span className="text-lg text-foreground/50 font-medium">/mo</span></div>
            <ul className="space-y-4 mb-8 flex-1 text-sm">
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>3 Free Valuations / Month</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Basic Price Estimates</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Save & Manage Properties</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Mortgage & Profit Calculators</span></li>
            </ul>
            <button className="w-full border-2 border-accent text-accent font-bold py-3 rounded-xl hover:bg-accent hover:text-white transition-colors" onClick={() => window.location.href='/register'}>
              Get Started
            </button>
          </div>

          {/* Premium Monthly Tier */}
          <div className="glass rounded-3xl p-8 shadow-sm border border-foreground/5 hover:border-accent/20 transition-colors flex flex-col">
            <h3 className="text-xl font-bold mb-2">Premium Subscriber</h3>
            <p className="text-sm text-foreground/60 mb-4 h-5">Monthly Billing</p>
            <div className="text-4xl font-extrabold mb-6">$29<span className="text-lg text-foreground/50 font-medium">/mo</span></div>
            <ul className="space-y-4 mb-8 flex-1 text-sm">
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Unlimited Valuations</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Download PDF Reports</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>AI Reasoning (SHAP) Insights</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Compare Multiple Units</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Market Sentiment Analysis</span></li>
            </ul>
            <button className="w-full border-2 border-accent text-accent font-bold py-3 rounded-xl hover:bg-accent hover:text-white transition-colors" onClick={() => window.location.href='/register'}>
              Upgrade Monthly
            </button>
          </div>

          {/* Premium Yearly Tier */}
          <div className="glass rounded-3xl p-8 shadow-xl border-2 border-accent relative flex flex-col transform md:-translate-y-4">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-accent text-white px-4 py-1 rounded-full text-sm font-bold tracking-wide whitespace-nowrap">
              SAVE 20% YEARLY
            </div>
            <h3 className="text-xl font-bold mb-2">Premium Subscriber</h3>
            <p className="text-sm text-foreground/60 mb-4 h-5">Billed Annually ($278/yr)</p>
            <div className="text-4xl font-extrabold mb-6">$23<span className="text-lg text-foreground/50 font-medium">/mo</span></div>
            <ul className="space-y-4 mb-8 flex-1 text-sm">
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Unlimited Valuations</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Download PDF Reports</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>AI Reasoning (SHAP) Insights</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Compare Multiple Units</span></li>
              <li className="flex items-center gap-3"><CheckCircle2 className="w-5 h-5 text-accent" /> <span>Market Sentiment Analysis</span></li>
            </ul>
            <button className="w-full bg-accent text-white font-bold py-3 rounded-xl hover:bg-accent/90 transition-colors shadow-lg shadow-accent/20" onClick={() => window.location.href='/register'}>
              Upgrade Yearly
            </button>
          </div>
        </div>
      </section>

      {/* Basic Footer */}
      <footer className="py-10 border-t border-foreground/5 text-center text-sm text-foreground/40">
        <p>&copy; {new Date().getFullYear()} HomeyAI. All rights reserved.</p>
      </footer>
    </main>
  );
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) {
  return (
    <div className="flex flex-col items-center group">
      <div className="w-12 h-12 rounded-xl bg-accent/5 flex items-center justify-center text-accent mb-4 group-hover:scale-110 transition-transform bg-white border border-transparent group-hover:border-accent/20 group-hover:shadow-lg">
        {icon}
      </div>
      <h3 className="text-lg font-bold mb-2">{title}</h3>
      <p className="text-sm text-foreground/50 leading-relaxed">{description}</p>
    </div>
  );
}
