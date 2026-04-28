"""Scatter Catalog — the warehouse behind the apps reveal.

Three sources, one surface:
  Suite — Scatter suite apps (read from ~/.local/share/applications/
          scatter-*.desktop for known slugs)
  Mine  — Ryann's own work, auto-detected from ~/projects, ~/scatter-academy,
          and ~/scatter-system itself. A repo qualifies if it has a
          package.json with a "scatter" field, OR a shipped .desktop file
          alongside it. Lower noise than blindly scanning every dir with
          a README.
  World — local AppStream cache (no network), via `appstreamcli search`.
          Renders name + summary + a copy-pasteable install command
          (apt or flatpak, whichever the metadata names).

stdlib only. Talks the same /tokens.css idiom as scatter-router so the
chrome stays aligned.
"""
import html
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# ── Paths ──────────────────────────────────────────────────────────────
HERE = Path(__file__).parent.resolve()
TOKENS_CSS = HERE.parent / "scatter-design-system" / "tokens.css"
APPS_DIR_USER = Path.home() / ".local" / "share" / "applications"
PROJECTS_ROOTS = [
    Path.home() / "projects",
    Path.home() / "scatter-academy",
    Path.home() / "scatter-system",
]


# ── Suite — read .desktop files ────────────────────────────────────────
# Order: home first (laptop forward surface), then catalog (warehouse).
SUITE_SLUGS = [
    "home",
    "catalog",
    "schools",
    "studio",
    "music",
    "write",
    "draft",
    "film",
    "stream",
]


def parse_desktop(path: Path) -> dict | None:
    """Extract Name/Comment/Exec/Icon from a .desktop file. Returns None
    if the file is missing or unreadable. Stdlib only — no GLib."""
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except Exception:
        return None
    fields = {}
    in_entry = False
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("[") and line.endswith("]"):
            in_entry = (line == "[Desktop Entry]")
            continue
        if not in_entry:
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.*)$", line)
        if not m:
            continue
        fields[m.group(1)] = m.group(2)
    return {
        "name":    fields.get("Name", path.stem),
        "comment": fields.get("Comment", ""),
        "exec":    fields.get("Exec", ""),
        "icon":    fields.get("Icon", ""),
    }


def list_suite() -> list[dict]:
    out = []
    for slug in SUITE_SLUGS:
        info = parse_desktop(APPS_DIR_USER / f"scatter-{slug}.desktop")
        if not info:
            continue
        out.append({
            "id": f"scatter-{slug}",
            "slug": slug,
            "name": info["name"],
            "comment": info["comment"],
            "icon": info["icon"],
            "source": "suite",
        })
    return out


# ── Mine — auto-detected user projects ────────────────────────────────
SKIP_DIR_NAMES = {"node_modules", ".git", ".next", "dist", "build", "__pycache__"}


def _qualify(child: Path) -> dict | None:
    """Decide whether `child` looks like an Ryann-authored Scatter app
    worth surfacing. Returns a tile dict if yes, None if no."""
    if not child.is_dir() or child.name.startswith("."):
        return None
    if child.name in SKIP_DIR_NAMES:
        return None
    pkg = child / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            name = data.get("name", "")
            if "scatter" in data or name.startswith("scatter-"):
                return {
                    "id": str(child),
                    "name": data.get("name", child.name),
                    "comment": data.get("description", ""),
                    "path": str(child),
                    "exec": "",
                    "source": "mine",
                }
        except Exception:
            pass
    desktops = list(child.glob("*.desktop"))
    if desktops:
        info = parse_desktop(desktops[0])
        if info:
            return {
                "id": str(child),
                "name": info["name"],
                "comment": info["comment"],
                "path": str(child),
                "exec": info["exec"],
                "source": "mine",
            }
    return None


def list_mine() -> list[dict]:
    """Walk PROJECTS_ROOTS up to two levels deep. The roots themselves
    are checked, then each child, then grandchildren. Once a directory
    qualifies, we stop descending into it — the project is the leaf as
    far as the catalog is concerned. Dedup by absolute path so an entry
    can't appear twice."""
    seen_paths: set[str] = set()
    candidates: list[dict] = []

    def consider(path: Path, depth: int):
        key = str(path.resolve())
        if key in seen_paths:
            return
        tile = _qualify(path)
        if tile:
            seen_paths.add(key)
            try:
                tile["_mtime"] = path.stat().st_mtime
            except OSError:
                tile["_mtime"] = 0
            candidates.append(tile)
            return
        if depth <= 0:
            return
        try:
            for child in sorted(path.iterdir()):
                consider(child, depth - 1)
        except (PermissionError, OSError):
            pass

    for root in PROJECTS_ROOTS:
        if not root.exists():
            continue
        consider(root, depth=2)

    # Dedup by package name — multiple checkouts of the same project
    # (e.g. two copies under ~/scatter-academy and ~/projects/scatter) collapse to
    # the most-recently-modified copy. Falls back to the path basename if
    # `name` is empty so unnamed projects don't all collide on "".
    by_name: dict[str, dict] = {}
    for c in candidates:
        key = c.get("name") or Path(c["path"]).name
        if key not in by_name or c["_mtime"] > by_name[key]["_mtime"]:
            by_name[key] = c
    out = sorted(by_name.values(), key=lambda x: x.get("name", ""))
    for tile in out:
        tile.pop("_mtime", None)
    return out


# ── World — AppStream local search ────────────────────────────────────
APPSTREAM_LIMIT = 40


def search_world(query: str) -> list[dict]:
    """Search the local AppStream cache. No network. Returns up to
    APPSTREAM_LIMIT results. Empty query returns [].

    `appstreamcli search` prints records like:

        Identifier: org.mozilla.firefox [desktop-application]
        Name: Firefox
        Summary: Fast, Private & Safe Web Browser
        Bundle: flatpak:app/org.mozilla.firefox/x86_64/stable
        ---
        Identifier: ...

    Records are separated by `---`. We split on those, then parse each
    record as `Key: value` lines."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        # appstreamcli has no --limit flag; we slice the result list
        # below to keep the surface tight.
        result = subprocess.run(
            ["appstreamcli", "search", q],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return [{"id": "_error", "name": "AppStream not available", "comment": str(e)}]

    records = result.stdout.split("\n---\n")
    out: list[dict] = []
    for record in records:
        record = record.strip()
        if not record:
            continue
        entry: dict = {"source": "world"}
        for line in record.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "Identifier":
                # Strip the "[desktop-application]" suffix.
                entry["id"] = value.split("[")[0].strip()
            elif key == "Name":
                entry["name"] = value
            elif key == "Summary":
                entry["comment"] = value
            elif key == "Package":
                entry["package"] = value
            elif key == "Bundle":
                # e.g. "flatpak:app/org.mozilla.firefox/x86_64/stable"
                if value.startswith("flatpak:"):
                    entry["flatpak"] = value[len("flatpak:"):]
                else:
                    entry["flatpak"] = value
        if entry.get("id"):
            out.append(entry)

    # Synthesize an install command for each result. Flatpak preferred over
    # apt because flatpak refs are unambiguous and don't require sudo.
    for entry in out:
        if entry.get("flatpak"):
            entry["install_cmd"] = f"flatpak install -y flathub {entry['flatpak']}"
        elif entry.get("package"):
            entry["install_cmd"] = f"sudo apt install {entry['package']}"
        else:
            entry["install_cmd"] = ""
    return out[:APPSTREAM_LIMIT]


# ── Launch dispatch ───────────────────────────────────────────────────
def launch(spec: dict) -> dict:
    """Given a tile spec, run its launcher. Suite tiles use gtk-launch
    against their .desktop; Mine tiles run their stored exec or open
    the project dir in Files; World tiles return the install command
    for the user to copy (no privileged install from a web UI)."""
    source = spec.get("source")
    if source == "suite":
        slug = spec.get("slug")
        if not slug or slug not in SUITE_SLUGS:
            return {"ok": False, "detail": "unknown suite slug"}
        try:
            subprocess.Popen(
                ["gtk-launch", f"scatter-{slug}.desktop"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {"ok": True, "launched": slug}
        except Exception as e:
            return {"ok": False, "detail": str(e)}

    if source == "mine":
        exec_cmd = spec.get("exec") or ""
        path = spec.get("path")
        if exec_cmd:
            try:
                subprocess.Popen(
                    ["bash", "-c", exec_cmd],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {"ok": True, "launched": exec_cmd}
            except Exception as e:
                return {"ok": False, "detail": str(e)}
        if path:
            try:
                subprocess.Popen(
                    ["xdg-open", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {"ok": True, "opened": path}
            except Exception as e:
                return {"ok": False, "detail": str(e)}
        return {"ok": False, "detail": "no exec or path"}

    if source == "world":
        # Don't run sudo apt or flatpak install from a web request — that's
        # exactly the privilege boundary feedback_data_leaves_consciously
        # exists to honor. Return the command for the user to run.
        return {
            "ok": False,
            "detail": "copy and run the install command in a terminal",
            "command": spec.get("install_cmd", ""),
        }

    return {"ok": False, "detail": "unknown source"}


# ── HTTP ──────────────────────────────────────────────────────────────
INDEX_HTML = HERE / "index.html"


class Handler(BaseHTTPRequestHandler):
    # Keep stdout clean; only log explicit messages.
    def log_message(self, fmt, *args):
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        if not path.exists():
            self.send_error(404, f"missing: {path.name}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/":
            return self._file(INDEX_HTML, "text/html")
        if path == "/tokens.css":
            return self._file(TOKENS_CSS, "text/css")
        if path == "/api/suite":
            return self._json(200, list_suite())
        if path == "/api/mine":
            return self._json(200, list_mine())
        if path == "/api/world":
            q = parse_qs(url.query).get("q", [""])[0]
            return self._json(200, search_world(q))
        self.send_error(404, "not found")

    def do_POST(self):
        if self.path != "/api/launch":
            self.send_error(404, "not found")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode() if length else ""
        try:
            spec = json.loads(body) if body else {}
        except Exception:
            return self._json(400, {"ok": False, "detail": "bad json"})
        return self._json(200, launch(spec))


def main():
    port = int(os.environ.get("PORT", "3070"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stdout.write(f"\n  Scatter Catalog at http://localhost:{port}\n\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
