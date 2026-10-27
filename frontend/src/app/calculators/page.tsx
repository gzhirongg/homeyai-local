"use client";

import { useState, useEffect } from "react";
import Navbar from "@/components/Navbar";
import { motion } from "framer-motion";
import { Calculator, Wallet, TrendingUp, ArrowRight, Info } from "lucide-react";

export default function CalculatorsPage() {
    const [loanAmount, setLoanAmount] = useState(500000);
    const [tenure, setTenure] = useState(25);
    const [interest, setInterest] = useState(3.5);
    const [monthlyPayment, setMonthlyPayment] = useState(0);

    const [buyPrice, setBuyPrice] = useState(500000);
    const [sellPrice, setSellPrice] = useState(650000);
    const [holdingCosts, setholdingCosts] = useState(20000);
    const [profit, setProfit] = useState(0);

    useEffect(() => {
        const r = interest / 100 / 12;
        const n = tenure * 12;
        const payment = (loanAmount * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
        setMonthlyPayment(payment);
    }, [loanAmount, tenure, interest]);

    useEffect(() => {
        setProfit(sellPrice - buyPrice - holdingCosts);
    }, [buyPrice, sellPrice, holdingCosts]);

    return (
        <main className="min-h-screen bg-slate-50 pb-20">
            <Navbar />

            <div className="max-w-7xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                <div className="mb-12 text-center">
                    <h1 className="text-4xl font-extrabold mb-4 tracking-tight">Financial Calculators</h1>
                    <p className="text-foreground/50 max-w-xl mx-auto">Plan your property journey with our integrated mortgage and profit estimators.</p>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
                    {/* Mortgage Calculator */}
                    <div className="glass rounded-3xl p-8 shadow-xl border-foreground/5">
                        <div className="flex items-center gap-3 mb-8">
                            <div className="w-12 h-12 rounded-2xl bg-accent/10 flex items-center justify-center text-accent">
                                <Calculator className="w-6 h-6" />
                            </div>
                            <div>
                                <h2 className="text-2xl font-bold">Mortgage Estimator</h2>
                                <p className="text-xs text-foreground/40">Calculate your monthly repayments</p>
                            </div>
                        </div>

                        <div className="space-y-8">
                            <CalcSlider
                                label="Loan Amount"
                                value={loanAmount}
                                min={100000}
                                max={2000000}
                                step={10000}
                                onChange={setLoanAmount}
                                unit="S$"
                            />
                            <CalcSlider
                                label="Loan Tenure"
                                value={tenure}
                                min={5}
                                max={35}
                                step={1}
                                onChange={setTenure}
                                unit="Years"
                            />
                            <CalcSlider
                                label="Interest Rate"
                                value={interest}
                                min={0.1}
                                max={10}
                                step={0.1}
                                onChange={setInterest}
                                unit="%"
                            />

                            <div className="p-8 rounded-3xl bg-accent text-white shadow-2xl shadow-accent/20 relative overflow-hidden mt-10">
                                <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16 blur-2xl" />
                                <p className="text-white/60 text-sm font-medium mb-2">Monthly Repayment</p>
                                <h3 className="text-4xl font-black">S${monthlyPayment.toLocaleString(undefined, { maximumFractionDigits: 0 })}</h3>
                                <div className="mt-4 pt-4 border-t border-white/20 flex justify-between text-xs font-medium text-white/80">
                                    <span>Total Payable: S${(monthlyPayment * tenure * 12).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Profit Calculator */}
                    <div className="glass rounded-3xl p-8 shadow-xl border-foreground/5">
                        <div className="flex items-center gap-3 mb-8">
                            <div className="w-12 h-12 rounded-2xl bg-secondary/10 flex items-center justify-center text-secondary">
                                <Wallet className="w-6 h-6" />
                            </div>
                            <div>
                                <h2 className="text-2xl font-bold">Profit/Loss Estimator</h2>
                                <p className="text-xs text-foreground/40">Estimate your potential return on investment</p>
                            </div>
                        </div>

                        <div className="space-y-6">
                            <div>
                                <label className="block text-sm font-medium mb-3">Purchase Price (S$)</label>
                                <input
                                    type="number"
                                    className="w-full bg-background border border-foreground/10 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-accent"
                                    value={buyPrice}
                                    onChange={(e) => setBuyPrice(Number(e.target.value))}
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-3">Predicted Selling Price (S$)</label>
                                <input
                                    type="number"
                                    className="w-full bg-background border border-foreground/10 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-accent"
                                    value={sellPrice}
                                    onChange={(e) => setSellPrice(Number(e.target.value))}
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-3">Holding Costs & Taxes (S$)</label>
                                <input
                                    type="number"
                                    className="w-full bg-background border border-foreground/10 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-accent"
                                    value={holdingCosts}
                                    onChange={(e) => setholdingCosts(Number(e.target.value))}
                                />
                            </div>

                            <div className={`p-8 rounded-3xl shadow-2xl relative overflow-hidden mt-10 transition-colors ${profit >= 0 ? "bg-secondary text-white shadow-secondary/20" : "bg-error text-white shadow-error/20"}`}>
                                <div className="absolute bottom-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mb-16 blur-2xl" />
                                <p className="text-white/60 text-sm font-medium mb-2">Potential {profit >= 0 ? "Profit" : "Loss"}</p>
                                <h3 className="text-4xl font-black">S${Math.abs(profit).toLocaleString()}</h3>
                                <div className="mt-4 pt-4 border-t border-white/20 flex justify-between text-xs font-medium text-white/80">
                                    <span>ROI: {((profit / buyPrice) * 100).toFixed(1)}%</span>
                                    <TrendingUp className="w-4 h-4" />
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    );
}

interface CalcSliderProps {
    label: string;
    value: number;
    min: number;
    max: number;
    step: number;
    onChange: (val: number) => void;
    unit: string;
}

function CalcSlider({ label, value, min, max, step, onChange, unit }: CalcSliderProps) {
    return (
        <div>
            <div className="flex justify-between items-center mb-4">
                <label className="text-sm font-bold text-foreground/70">{label}</label>
                <div className="px-3 py-1 rounded-lg bg-foreground/5 border border-foreground/5 text-sm font-black text-accent">
                    {unit === "S$" ? `${unit}${value.toLocaleString()}` : `${value} ${unit}`}
                </div>
            </div>
            <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value}
                onChange={(e) => onChange(Number(e.target.value))}
                className="w-full h-1.5 bg-foreground/10 rounded-full appearance-none cursor-pointer accent-accent"
            />
        </div>
    )
}
