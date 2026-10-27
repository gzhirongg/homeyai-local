"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
    AUTOCOMPLETE_DEBOUNCE_MS,
    MIN_QUERY_LEN,
    searchProperties,
    type PropertySearchHit,
} from "@/lib/propertySearch";

type UsePropertyAutocompleteOptions = {
    query: string;
    /** When false, skip fetching (e.g. selection tag visible). */
    enabled: boolean;
};

export function usePropertyAutocomplete({
    query,
    enabled,
}: UsePropertyAutocompleteOptions) {
    const [hits, setHits] = useState<PropertySearchHit[]>([]);
    const [loading, setLoading] = useState(false);
    const [noResults, setNoResults] = useState(false);
    const [activeIndex, setActiveIndex] = useState(-1);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const listRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!enabled) return;
        if (debounceRef.current) clearTimeout(debounceRef.current);

        debounceRef.current = setTimeout(() => {
            const t = query.trim();
            if (t.length < MIN_QUERY_LEN) {
                setHits([]);
                setNoResults(false);
                setActiveIndex(-1);
                return;
            }

            setLoading(true);
            setNoResults(false);
            void searchProperties(t)
                .then((list) => {
                    setHits(list);
                    setNoResults(list.length === 0);
                    setActiveIndex(list.length > 0 ? 0 : -1);
                })
                .catch(() => {
                    setHits([]);
                    setNoResults(true);
                    setActiveIndex(-1);
                })
                .finally(() => setLoading(false));
        }, AUTOCOMPLETE_DEBOUNCE_MS);

        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [query, enabled]);

    const scrollActiveIntoView = useCallback((index: number) => {
        if (index < 0 || !listRef.current) return;
        const el = listRef.current.querySelector<HTMLElement>(
            `[data-hit-index="${index}"]`
        );
        el?.scrollIntoView({ block: "nearest" });
    }, []);

    const handleListKeyDown = useCallback(
        (
            e: React.KeyboardEvent,
            opts: {
                open: boolean;
                setOpen: (v: boolean) => void;
                pickHit: (hit: PropertySearchHit) => void;
            }
        ) => {
            const { open, setOpen, pickHit } = opts;
            if (!open || hits.length === 0) return false;

            if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIndex((i) => {
                    const next = Math.min(i < 0 ? 0 : i + 1, hits.length - 1);
                    scrollActiveIntoView(next);
                    return next;
                });
                return true;
            }
            if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIndex((i) => {
                    const next = Math.max(i < 0 ? 0 : i - 1, 0);
                    scrollActiveIntoView(next);
                    return next;
                });
                return true;
            }
            if (e.key === "Enter") {
                if (activeIndex >= 0 && activeIndex < hits.length) {
                    e.preventDefault();
                    pickHit(hits[activeIndex]);
                    return true;
                }
            }
            if (e.key === "Escape") {
                e.preventDefault();
                setOpen(false);
                setActiveIndex(-1);
                return true;
            }
            return false;
        },
        [hits, activeIndex, scrollActiveIntoView]
    );

    const resetList = useCallback(() => {
        setHits([]);
        setNoResults(false);
        setActiveIndex(-1);
    }, []);

    return {
        hits,
        loading,
        noResults,
        activeIndex,
        setActiveIndex,
        listRef,
        handleListKeyDown,
        resetList,
    };
}
