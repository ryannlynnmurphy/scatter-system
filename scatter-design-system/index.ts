/**
 * @scatter/shell — shared chrome for the Scatter suite.
 *
 * Every Scatter Next app (Music, Film, Write, Schools) consumes this
 * package so the suite has one keyboard contract, one design token system,
 * one button spec. When something here changes, the whole suite changes.
 *
 *   import { EscapeContract } from "@scatter/shell";
 *   import "@scatter/shell/tokens.css";
 *   import "@scatter/shell/buttons.css";
 *
 * The tokens.css file ships CSS variables that every component below
 * references. GNOME Shell stylesheets mirror these values inline because
 * GNOME CSS doesn't support variables reliably.
 */

export { default as EscapeContract } from "./EscapeContract";
export { default as ScatterBar } from "./ScatterBar";
export type {
  ScatterProject,
  ScatterProjectFile,
  ScatterProjectManifest,
  ScatterProjectSummary,
  ScatterTool,
} from "./ScatterBar";
