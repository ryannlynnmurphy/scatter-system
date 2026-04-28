"use client";

import { useEffect, useState } from "react";

/**
 * @scatter/shell — ScatterBar
 *
 * The single chrome bar shared by every Scatter Next app (Music, Film,
 * Write, future surfaces). Owns:
 *   - current project name + dir (read-only display)
 *   - New project (prompt + POST)
 *   - Open project (dropdown of existing projects)
 *   - Open All (launches every populated file in the current project)
 *   - Tools dropdown (filtered by discipline; launches a specific tool with
 *     the project's matching file if it exists)
 *
 * Each consumer hands in:
 *   - project / setProject — the shared state
 *   - disciplines           — which slice of the catalog to show in Tools
 *
 * Stylistically the bar is identical across apps because the styles
 * reference only the shared scatter tokens. A change here propagates
 * everywhere on the next `npm run shell:sync` (or postinstall).
 *
 * The dropdowns animate in with a 220ms ease — the canon Manicured Motion.
 * No abrupt cuts, no spring overshoot — durational, composed.
 */

export type ScatterProjectManifest = {
  slug: string;
  name: string;
  createdAt: string;
};

export type ScatterProjectFile = {
  tool: string;
  rel: string;
  abs: string;
  exists: boolean;
};

export type ScatterProject = {
  manifest: ScatterProjectManifest;
  dir: string;
  files: ScatterProjectFile[];
};

export type ScatterProjectSummary = {
  slug: string;
  name: string;
  createdAt: string;
};

export type ScatterTool = {
  id: string;
  label: string;
  discipline: "audio" | "film" | "graphics" | "model" | "write" | "code";
  blurb: string;
  bin_candidates: string[];
  file_pattern: string | null;
  subdir: string | null;
};

async function fetchList(): Promise<ScatterProjectSummary[]> {
  const res = await fetch("/api/project");
  if (!res.ok) return [];
  const data = (await res.json()) as { projects?: ScatterProjectSummary[] };
  return data.projects ?? [];
}

async function fetchProjectByslug(slug: string): Promise<ScatterProject | null> {
  const res = await fetch(`/api/project/${encodeURIComponent(slug)}`);
  if (!res.ok) return null;
  const data = (await res.json()) as { project?: ScatterProject };
  return data.project ?? null;
}

async function createProject(
  name: string,
): Promise<{ project?: ScatterProject; error?: string }> {
  const res = await fetch("/api/project", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = (await res.json().catch(() => ({}))) as {
    project?: ScatterProject;
    error?: string;
  };
  if (!res.ok) return { error: data.error ?? `HTTP ${res.status}` };
  return { project: data.project };
}

async function fetchTools(disciplines: string[]): Promise<ScatterTool[]> {
  const res = await fetch("/api/tools");
  if (!res.ok) return [];
  const data = (await res.json()) as { tools?: ScatterTool[] };
  if (disciplines.length === 0) return data.tools ?? [];
  const set = new Set(disciplines);
  return (data.tools ?? []).filter((t) => set.has(t.discipline));
}

async function launchTool(
  tool: string,
  slug: string | null,
): Promise<string | null> {
  const res = await fetch("/api/launch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, project: slug ?? undefined }),
  });
  const data = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) return data.error ?? `HTTP ${res.status}`;
  return null;
}

const PANEL: React.CSSProperties = {
  position: "absolute",
  right: 0,
  top: "100%",
  marginTop: "0.35rem",
  zIndex: 10,
  minWidth: "16rem",
  maxHeight: "20rem",
  overflow: "auto",
  border: "1px solid rgba(255,255,255,0.12)",
  background: "var(--scatter-ink)",
  borderRadius: "3px",
  listStyle: "none",
  padding: 0,
  boxShadow: "0 12px 32px rgba(0,0,0,0.55)",
  // Curtain reveal — slide-down + fade-in. 220ms ease, the canon.
  animation: "scatterReveal 220ms cubic-bezier(0.2, 0.8, 0.2, 1)",
};

const ROW_BTN: React.CSSProperties = {
  width: "100%",
  textAlign: "left",
  padding: "0.55rem 0.75rem",
  background: "transparent",
  border: "none",
  cursor: "pointer",
  fontSize: "0.7rem",
  color: "var(--scatter-bright)",
  fontFamily: "inherit",
};

export default function ScatterBar({
  project,
  setProject,
  disciplines = [],
}: {
  project: ScatterProject | null;
  setProject: (p: ScatterProject | null) => void;
  disciplines?: string[];
}) {
  const [list, setList] = useState<ScatterProjectSummary[]>([]);
  const [tools, setTools] = useState<ScatterTool[]>([]);
  const [openProjects, setOpenProjects] = useState(false);
  const [openTools, setOpenTools] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchList().then(setList);
    fetchTools(disciplines).then(setTools);
    // disciplines is a prop array; consumers should pass a stable reference
    // or the project on remount will pick up the latest tool catalog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, disciplines.join(",")]);

  const onNew = async () => {
    const name = window.prompt("Project name?")?.trim();
    if (!name) return;
    setBusy(true);
    setMsg(null);
    const { project: created, error } = await createProject(name);
    setBusy(false);
    if (error) {
      setMsg(error);
      return;
    }
    if (created) setProject(created);
  };

  const onPick = async (slug: string) => {
    setOpenProjects(false);
    setBusy(true);
    setMsg(null);
    const p = await fetchProjectByslug(slug);
    setBusy(false);
    if (!p) setMsg("Could not load project.");
    else setProject(p);
  };

  const onLaunchTool = async (id: string) => {
    setOpenTools(false);
    setBusy(true);
    setMsg(null);
    const err = await launchTool(id, project?.manifest.slug ?? null);
    setBusy(false);
    if (err) setMsg(err);
    else setMsg(`Started ${id}.`);
  };

  const onOpenAll = async () => {
    if (!project) return;
    const populated = project.files.filter((f) => f.exists).map((f) => f.tool);
    if (populated.length === 0) {
      setMsg("No saved files yet — open and save once in each app.");
      return;
    }
    setBusy(true);
    setMsg(null);
    const errors: string[] = [];
    for (const t of populated) {
      const err = await launchTool(t, project.manifest.slug);
      if (err) errors.push(`${t}: ${err}`);
    }
    setBusy(false);
    setMsg(errors.length ? errors.join(" · ") : `Opened ${populated.length}.`);
  };

  const fileFor = (id: string) =>
    project?.files.find((f) => f.tool === id);

  return (
    <>
      <style>{`
        @keyframes scatterReveal {
          from { opacity: 0; transform: translateY(-8px); }
          to   { opacity: 1; transform: translateY(0);     }
        }
      `}</style>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.5rem 1rem",
          borderBottom: "1px solid rgba(255,255,255,0.08)",
          background: "var(--scatter-black)",
          fontSize: "0.75rem",
          fontFamily: "var(--scatter-mono)",
          color: "var(--scatter-bright)",
          flexShrink: 0,
        }}
      >
        <span style={{ color: "var(--scatter-quiet)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          project
        </span>
        <span style={{ color: project ? "var(--scatter-green)" : "var(--scatter-quiet)" }}>
          {project ? project.manifest.name : "(none)"}
        </span>

        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: "0.35rem",
            position: "relative",
          }}
        >
          <button
            type="button"
            disabled={busy}
            onClick={onNew}
            style={{
              padding: "0.3rem 0.7rem",
              border: "1px solid rgba(255,255,255,0.10)",
              borderRadius: "2px",
              background: "transparent",
              cursor: "pointer",
              fontSize: "0.7rem",
              color: "var(--scatter-bright)",
              fontFamily: "inherit",
              opacity: busy ? 0.5 : 1,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            New
          </button>

          <div style={{ position: "relative" }}>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setOpenProjects((v) => !v);
                setOpenTools(false);
              }}
              style={{
                padding: "0.3rem 0.7rem",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: "2px",
                background: "transparent",
                cursor: "pointer",
                fontSize: "0.7rem",
                color: "var(--scatter-bright)",
                fontFamily: "inherit",
                opacity: busy ? 0.5 : 1,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
              }}
            >
              Open
            </button>
            {openProjects && (
              <ul style={PANEL}>
                {list.length === 0 && (
                  <li style={{ padding: "0.5rem 0.75rem", color: "var(--scatter-quiet)", fontSize: "0.7rem" }}>
                    No projects yet.
                  </li>
                )}
                {list.map((p) => (
                  <li key={p.slug}>
                    <button type="button" onClick={() => onPick(p.slug)} style={ROW_BTN}>
                      <div>{p.name}</div>
                      <div style={{ color: "var(--scatter-quiet)", marginTop: "0.15rem" }}>{p.slug}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            type="button"
            disabled={busy || !project}
            onClick={onOpenAll}
            style={{
              padding: "0.3rem 0.7rem",
              borderRadius: "2px",
              background: project ? "var(--scatter-green)" : "transparent",
              color: project ? "var(--scatter-black)" : "var(--scatter-quiet)",
              border: project ? "none" : "1px solid rgba(255,255,255,0.10)",
              cursor: project ? "pointer" : "not-allowed",
              fontSize: "0.7rem",
              fontFamily: "inherit",
              fontWeight: 600,
              opacity: busy ? 0.5 : 1,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            Open All
          </button>

          {tools.length > 0 && (
            <div style={{ position: "relative" }}>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setOpenTools((v) => !v);
                  setOpenProjects(false);
                }}
                style={{
                  padding: "0.3rem 0.7rem",
                  border: "1px solid var(--scatter-green-edge)",
                  borderRadius: "2px",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: "0.7rem",
                  color: "var(--scatter-green)",
                  fontFamily: "inherit",
                  opacity: busy ? 0.5 : 1,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}
              >
                Tools ▾
              </button>
              {openTools && (
                <ul style={PANEL}>
                  {tools.map((t) => {
                    const file = fileFor(t.id);
                    return (
                      <li key={t.id}>
                        <button type="button" onClick={() => onLaunchTool(t.id)} style={ROW_BTN}>
                          <div
                            style={{
                              display: "flex",
                              alignItems: "baseline",
                              justifyContent: "space-between",
                              gap: "0.5rem",
                            }}
                          >
                            <span style={{ color: "var(--scatter-bright)" }}>{t.label}</span>
                            {project && file && (
                              <span style={{ color: file.exists ? "var(--scatter-green)" : "var(--scatter-quiet)" }}>
                                {file.exists ? "●" : "○"}
                              </span>
                            )}
                          </div>
                          <div style={{ color: "var(--scatter-quiet)", marginTop: "0.15rem" }}>{t.blurb}</div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
        {msg && (
          <span
            style={{
              flexBasis: "100%",
              color: "var(--scatter-amber)",
              fontSize: "0.7rem",
              marginTop: "0.25rem",
            }}
          >
            {msg}
          </span>
        )}
      </div>
    </>
  );
}
