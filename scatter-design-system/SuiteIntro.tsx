"use client";

import { useEffect, useState } from "react";

/**
 * SuiteIntro — a brief black overlay with the Scatter face, fading away
 * to reveal the app. Every Scatter Next app boots through it so the suite
 * feels like one room with one entrance.
 *
 * Timing matches the Manicured Motion canon:
 *   0–150ms   hold black with `>-<` centered, full opacity
 *   150–500ms fade to app, 350ms ease-out
 *   500ms+    overlay unmounts, app is fully interactive
 *
 * Total drag on the user is ~half a second, traded for the keynote moment.
 * The intro respects prefers-reduced-motion: users who've opted out of
 * animations get the app instantly with no overlay.
 *
 * If multiple apps are switched between in rapid succession, each app's
 * intro fires on its own load — the bar's app-switch dedupe (Slice 2)
 * means clicks don't re-spawn windows, so this isn't gratuitous.
 *
 * A failsafe timer always clears the overlay — if hydration or timers fail,
 * the old behavior left a fullscreen blocking layer indefinitely.
 */
const SUITE_INTRO_FAILSAFE_MS = 3000;

export default function SuiteIntro() {
  const [phase, setPhase] = useState<"hold" | "fade" | "gone">("hold");

  useEffect(() => {
    const failSafe = window.setTimeout(() => setPhase("gone"), SUITE_INTRO_FAILSAFE_MS);
    return () => window.clearTimeout(failSafe);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setPhase("gone");
      return;
    }
    const t1 = setTimeout(() => setPhase("fade"), 150);
    const t2 = setTimeout(() => setPhase("gone"), 500);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  if (phase === "gone") return null;

  return (
    <div
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2147483646,
        background: "var(--scatter-black, #0a0a0a)",
        color: "var(--scatter-green, #00ff88)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--scatter-mono, 'JetBrains Mono', monospace)",
        fontSize: "3rem",
        letterSpacing: "0.18em",
        opacity: phase === "fade" ? 0 : 1,
        transition: "opacity 350ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        pointerEvents: phase === "fade" ? "none" : "auto",
        userSelect: "none",
      }}
    >
      {">-<"}
    </div>
  );
}
