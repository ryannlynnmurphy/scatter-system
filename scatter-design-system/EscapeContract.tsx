"use client";

import { useEffect, useState } from "react";

/**
 * The escape contract — invariant across every Scatter surface.
 *
 *   Esc        → close the focused window.
 *   Ctrl+W     → same.
 *   Visible ×  → fixed top-right of every Scatter app, always clickable.
 *
 * Chromium's --app= mode strips window decorations, so undecorated Scatter
 * apps would otherwise be a trap. This component is the second arm of the
 * escape pair: per-window close. The bar's bowtie right-click is the
 * other arm — minimize-all without killing.
 *
 * Esc is suppressed inside text fields so a draft mid-keystroke isn't
 * window.close()d. Ctrl+W is unconditional — it's an explicit gesture.
 *
 * This component is the canonical source. Music / Film / Write consume it
 * via `import { EscapeContract } from "@scatter/shell"`.
 */
export default function EscapeContract() {
  const [hover, setHover] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        const tag = (e.target as HTMLElement | null)?.tagName;
        const editable = (e.target as HTMLElement | null)?.isContentEditable;
        if (tag === "INPUT" || tag === "TEXTAREA" || editable) return;
        window.close();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "w") {
        e.preventDefault();
        window.close();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <button
      type="button"
      onClick={() => window.close()}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title="Close (Esc)"
      aria-label="Close"
      style={{
        position: "fixed",
        top: 8,
        right: 8,
        width: 28,
        height: 28,
        borderRadius: 4,
        border: "1px solid rgba(255,255,255,0.15)",
        background: hover ? "rgba(255,80,80,0.92)" : "rgba(0,0,0,0.55)",
        color: hover ? "#fff" : "rgba(255,255,255,0.85)",
        fontSize: 16,
        lineHeight: "26px",
        textAlign: "center",
        cursor: "pointer",
        padding: 0,
        zIndex: 2147483647,
        fontFamily: "system-ui, sans-serif",
        transition: "background 120ms ease, color 120ms ease",
      }}
    >
      ×
    </button>
  );
}
