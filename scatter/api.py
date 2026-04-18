#!/usr/bin/env python3
"""
scatter/api.py — the single vetted path for external network calls.

Every outbound call to a non-localhost service goes through this module.
Anything else in the codebase that imports urllib/requests/httpx/socket for
a non-localhost destination is a leak. The enforcement test in
scatter/tests/test_leak_free.sh asserts this architecturally.

Legibility:
- Every adapter starts with scatter_core.assert_researcher() — learner
  profile refuses by construction.
- Every call opens an audit entry (audit_begin) and closes it
  (audit_commit / audit_fail). The audit log never records the content
  of prompts or responses, only metadata: service, endpoint, byte sizes,
  elapsed time, and the model / estimated watts.
- Content is the private data. Metadata is the legible cost.

Revocability:
- scatter_core.forget(audit_id) tombstones an entry. Upstream retention
  is noted in the begin entry so the user can see whose policy still
  applies after local deletion.

Stdlib only, except for the explicit dependency surface declared in
README (task #13). No requests, no httpx, no external SDKs.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


# ---------- endpoints (documented single-origin for each service) ----------

CLAUDE_ENDPOINT = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

# Upstream retention declarations. These are stated by the providers and
# are shown to the user when they inspect an audit entry. If a provider
# changes its retention policy, this table needs updating (task for the
# README: audit retention re-verification cadence).
UPSTREAM_RETENTION = {
    "claude": "Anthropic default retention applies; see provider TOS",
    "tavily": "Tavily default retention applies; see provider TOS",
    "claude_code": "Anthropic Claude Code SDK retention applies; see provider TOS",
}


# ---------- helpers ----------

def _api_key(service_name: str) -> str:
    """Read API key from config.json or environment. Never logged."""
    cfg = sc.config_read()
    keys = cfg.get("apis", {})
    key = keys.get(service_name, "")
    if not key:
        # Allow env var fallback for dev convenience
        env_name = {
            "claude": "ANTHROPIC_API_KEY",
            "tavily": "TAVILY_API_KEY",
            "claude_code": "ANTHROPIC_API_KEY",
        }.get(service_name, "")
        if env_name:
            key = os.environ.get(env_name, "")
    if not key:
        raise RuntimeError(
            f"no api key for {service_name}. set it via "
            f"`scatter profile --set researcher` then edit "
            f"~/.scatter/config.json → apis.{service_name}"
        )
    return key


def _summarize_payload(payload: dict) -> str:
    """Metadata-only summary. Never the content."""
    # Try to count tokens-ish (just chars/4 is a rough estimate)
    total_chars = 0
    msg_count = 0
    if "messages" in payload:
        msg_count = len(payload["messages"])
        for m in payload["messages"]:
            content = m.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
    elif "query" in payload:
        total_chars = len(payload["query"])
    return f"{msg_count} messages, ~{total_chars // 4} est tokens, {total_chars} chars"


def _summarize_response(body: bytes, kind: str) -> str:
    """Metadata-only response summary."""
    size = len(body)
    try:
        data = json.loads(body)
        if kind == "claude" and "content" in data:
            pieces = data.get("content", [])
            text = "".join(p.get("text", "") for p in pieces if p.get("type") == "text")
            return f"{len(text)} chars, stop={data.get('stop_reason', '?')}"
        if kind == "tavily" and "results" in data:
            return f"{len(data.get('results', []))} results, answer={'yes' if data.get('answer') else 'no'}"
    except (json.JSONDecodeError, AttributeError):
        pass
    return f"{size} bytes"


def _call_json(url: str, payload: dict, headers: dict, service: str, kind: str) -> dict:
    """Shared wrapper: assert_researcher → audit_begin → urlopen → audit_commit."""
    sc.assert_researcher(f"{service} API call")

    body_bytes = json.dumps(payload).encode()
    audit_id = sc.audit_begin(
        service=service,
        endpoint=url,
        payload_summary=_summarize_payload(payload),
    )

    t0 = time.monotonic()
    try:
        req = Request(url, data=body_bytes, headers=headers, method="POST")
        with urlopen(req, timeout=120) as resp:
            response_bytes = resp.read()
            status = resp.status
        elapsed = time.monotonic() - t0
        sc.audit_commit(
            audit_id,
            response_summary=_summarize_response(response_bytes, kind),
            bytes_out=len(body_bytes),
            bytes_in=len(response_bytes),
            # Local watts for client side only — upstream watts are not
            # accountable to us; stated as zero here so the legibility
            # claim is truthful about what we can measure.
            watts_est=0.0,
        )
        if status >= 400:
            raise RuntimeError(f"{service} returned {status}")
        return json.loads(response_bytes)
    except HTTPError as e:
        err_body = e.read().decode(errors="replace")[:200]
        sc.audit_fail(audit_id, error=f"HTTP {e.code}: {err_body}")
        raise
    except URLError as e:
        sc.audit_fail(audit_id, error=f"URL error: {e.reason}")
        raise
    except Exception as e:
        sc.audit_fail(audit_id, error=f"{type(e).__name__}: {e}")
        raise


# ---------- adapters ----------

def claude_chat(
    prompt: str,
    system: str | None = None,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
) -> dict:
    """Call Anthropic Claude. Returns the parsed response dict.

    Only callable under researcher profile. Audit-logged. No API key → RuntimeError."""
    # Profile check comes FIRST — before key lookup — so a learner with a
    # stored key still refuses on the profile, not on key availability.
    # Architectural order matters for the claim to be honest.
    sc.assert_researcher("claude_chat")
    key = _api_key("claude")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": CLAUDE_API_VERSION,
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    return _call_json(CLAUDE_ENDPOINT, payload, headers, "claude", "claude")


def tavily_search(query: str, search_depth: str = "basic", max_results: int = 5) -> dict:
    """Tavily research-grade web search. Returns parsed response."""
    sc.assert_researcher("tavily_search")
    key = _api_key("tavily")
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": True,
    }
    return _call_json(TAVILY_ENDPOINT, payload, headers, "tavily", "tavily")


def claude_code(
    prompt: str,
    cwd: str | None = None,
    timeout_s: int = 300,
    binary: str = "claude",
) -> dict:
    """Invoke the local Claude Code CLI with a prompt, via subprocess.

    The CLI itself handles auth (via the user's ~/.claude/ credentials)
    and makes the external API calls. Scatter does not touch Anthropic's
    API directly for this path — we delegate to the tool the user already
    uses.

    Audit-logged like the HTTP adapters: begin when we launch the subprocess,
    commit on success with the length of the response, fail on nonzero exit.
    The prompt text is NOT logged (it's content, not metadata).

    Architectural note: this adapter uses subprocess rather than urllib, but
    the claim "scatter/api.py is the only place external traffic originates"
    still holds — we are the only module that spawns a child process expected
    to open external sockets. The leak-free test currently scans for Python
    imports of urllib/requests; a future version should also check for
    subprocess.run/Popen outside this file when the target is a network-
    capable binary. For now, convention + code review."""
    import subprocess
    import shutil

    sc.assert_researcher("claude_code")

    claude_bin = shutil.which(binary) or os.path.expanduser(f"~/.local/bin/{binary}")
    if not Path(claude_bin).exists():
        raise RuntimeError(
            f"claude CLI not found (looked in PATH and ~/.local/bin/{binary}). "
            f"Install from: https://docs.anthropic.com/en/docs/claude-code"
        )

    audit_id = sc.audit_begin(
        service="claude_code",
        endpoint=claude_bin,
        payload_summary=f"{len(prompt)} chars",
    )

    try:
        # -p = print-only non-interactive mode: CLI reads prompt, prints
        # response, exits. No tty allocation needed.
        result = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True,
            timeout=timeout_s,
            text=True,
            cwd=cwd,
        )
        response = result.stdout
        if result.returncode != 0:
            err = (result.stderr or "")[:300]
            sc.audit_fail(audit_id, error=f"exit {result.returncode}: {err}")
            raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {err}")
        sc.audit_commit(
            audit_id,
            response_summary=f"{len(response)} chars",
            bytes_out=len(prompt.encode()),
            bytes_in=len(response.encode()),
            watts_est=0.0,
        )
        return {"response": response, "returncode": result.returncode}
    except subprocess.TimeoutExpired as e:
        sc.audit_fail(audit_id, error=f"timeout after {timeout_s}s")
        raise RuntimeError(f"claude CLI timed out after {timeout_s}s") from e
    except Exception as e:
        sc.audit_fail(audit_id, error=f"{type(e).__name__}: {e}")
        raise


# ---------- smoke self-check (does not call out) ----------

def self_check() -> dict:
    """Verify the module's architectural claims without hitting any API.

    Returns {ok: bool, checks: [...]}.
    """
    checks = []

    # 1. Learner profile refuses
    original = sc.profile()
    try:
        sc.set_profile("learner")
        try:
            claude_chat("test")
            checks.append(("learner refuses claude_chat", False, "did not raise"))
        except sc.ProfileMismatch:
            checks.append(("learner refuses claude_chat", True, "raised ProfileMismatch"))
        except RuntimeError as e:
            # If there's no API key it might raise earlier, before assert —
            # that would be a bug. Check assert comes first.
            checks.append(("learner refuses claude_chat", False, f"raised {type(e).__name__} before assert_researcher"))
    finally:
        sc.set_profile(original)

    # 2. Researcher without key raises RuntimeError (not ProfileMismatch)
    sc.set_profile("researcher")
    cfg = sc.config_read()
    keys_before = cfg.get("apis", {})
    cfg["apis"] = {}
    sc.config_write(cfg)
    # Also clear env var for this check
    saved_env = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        try:
            claude_chat("test")
            checks.append(("researcher without key raises", False, "did not raise"))
        except RuntimeError as e:
            if "no api key" in str(e):
                checks.append(("researcher without key raises", True, "raised RuntimeError as expected"))
            else:
                checks.append(("researcher without key raises", False, f"wrong message: {e}"))
        except Exception as e:
            checks.append(("researcher without key raises", False, f"wrong type: {type(e).__name__}"))
    finally:
        cfg["apis"] = keys_before
        sc.config_write(cfg)
        if saved_env is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved_env

    # 3. claude_code refuses under learner profile (same gate as the other adapters)
    sc.set_profile("learner")
    try:
        try:
            claude_code("refused under learner")
            checks.append(("learner refuses claude_code", False, "did not raise"))
        except sc.ProfileMismatch:
            checks.append(("learner refuses claude_code", True, "raised ProfileMismatch"))
        except Exception as e:
            checks.append(("learner refuses claude_code", False, f"wrong exception: {type(e).__name__}"))
    finally:
        sc.set_profile("researcher")

    ok = all(passed for _, passed, _ in checks)
    return {"ok": ok, "checks": checks}


if __name__ == "__main__":
    if "--self-check" in sys.argv or "--check" in sys.argv:
        result = self_check()
        for name, passed, detail in result["checks"]:
            marker = "✓" if passed else "✗"
            print(f"  {marker} {name} — {detail}")
        print("\nall pass" if result["ok"] else "\nFAILED")
        sys.exit(0 if result["ok"] else 1)
    print("scatter/api.py — the vetted external-call path. Run with --self-check to verify.")
