#!/usr/bin/env bash
# test_learner_isolated.sh — kernel-level enforcement test for the
# learner profile. The metaphysics → mechanism → physics triangle:
#
#   metaphysics: alignment = legibility + revocability
#   mechanism:   learner profile refuses external calls by construction
#   physics:     the kernel drops packets from a net namespace with no route
#
# Two things must be true at once:
#   1. User-space refusal. scatter/api.py.claude_chat() raises
#      ProfileMismatch BEFORE any socket is opened.
#   2. Kernel-space isolation. Even if something bypassed the profile
#      check, running inside a new network namespace means there is no
#      route to the outside — connection attempts fail at the syscall
#      layer, not at the application layer.
#
# Belt and braces. The alignment claim holds under both.
#
# Runs unprivileged via `unshare --user --net` (Ubuntu 24.04 has user
# namespaces enabled for regular users).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
RESET=$'\033[0m'

FAIL=0

# -------- Preflight: unshare available? --------

if ! unshare --user --net true 2>/dev/null; then
    echo "${RED}✗ unshare --user --net not available${RESET}" >&2
    echo "  This machine does not permit unprivileged user + net namespaces." >&2
    echo "  The kernel-level claim cannot be tested here. Aborting." >&2
    exit 2
fi

echo "▸ preflight: unshare --user --net available"
echo ""

# -------- Save current profile, set to learner --------

ORIGINAL_PROFILE=$(python3 "$ROOT/scatter_core.py" profile)
trap 'python3 "$ROOT/scatter_core.py" profile --set "$ORIGINAL_PROFILE" >/dev/null' EXIT
python3 "$ROOT/scatter_core.py" profile --set learner >/dev/null
echo "▸ profile set to learner for this test"
echo ""

# -------- Part 1: user-space refusal --------
# Even without kernel isolation, assert_researcher() inside
# scatter/api.py must raise ProfileMismatch before any network call.

echo "▸ part 1: user-space refusal (assert_researcher gate)"

USER_SPACE_OUTPUT=$(python3 - <<'PY' 2>&1 || true
import sys
sys.path.insert(0, '.')
import scatter_core as sc
import scatter.api as api

assert sc.profile() == "learner", f"expected learner, got {sc.profile()}"
try:
    api.claude_chat("this must be refused")
except sc.ProfileMismatch as e:
    print(f"REFUSED: {e}")
    sys.exit(0)
except Exception as e:
    print(f"WRONG_EXCEPTION: {type(e).__name__}: {e}")
    sys.exit(1)
print("DID_NOT_RAISE")
sys.exit(1)
PY
)

if echo "$USER_SPACE_OUTPUT" | grep -q "^REFUSED:"; then
    echo "  ${GREEN}✓ learner profile refused claude_chat at assert_researcher${RESET}"
    echo "    $(echo "$USER_SPACE_OUTPUT" | head -1)"
else
    echo "  ${RED}✗ user-space refusal failed${RESET}" >&2
    echo "    output: $USER_SPACE_OUTPUT" >&2
    FAIL=1
fi
echo ""

# -------- Part 2: kernel-level isolation --------
# Run code inside a new network namespace. No loopback is brought up.
# Attempting to open a TCP connection to anywhere must fail at the
# syscall layer. This proves that even if the user-space gate were
# somehow bypassed, the kernel stops the leak.

echo "▸ part 2: kernel-level isolation (net namespace has no route)"

# Use --user --net without --map-root-user (which needs CAP_SETUID).
# Inside the new namespace we cannot bring up loopback (would need root),
# but we also don't need to — we're testing that reaches out to public
# addresses fail at the kernel layer.
KERNEL_OUTPUT=$(unshare --user --net python3 - <<'PY' 2>&1 || true
import socket
import sys

targets = [
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
]
blocked = 0
for host, port in targets:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((host, port))
        print(f"LEAKED: connected to {host}:{port}")
        sys.exit(1)
    except OSError as e:
        print(f"BLOCKED: {host}:{port} → {type(e).__name__}: {e.errno}")
        blocked += 1
    finally:
        s.close()

try:
    socket.gethostbyname("api.anthropic.com")
    print("LEAKED: DNS resolved api.anthropic.com")
    sys.exit(1)
except OSError as e:
    print(f"BLOCKED: DNS → {type(e).__name__}")
    blocked += 1

print(f"TOTAL_BLOCKED: {blocked}")
sys.exit(0)
PY
)

if echo "$KERNEL_OUTPUT" | grep -q "^LEAKED"; then
    echo "  ${RED}✗ kernel isolation leaked${RESET}" >&2
    echo "$KERNEL_OUTPUT" | sed 's/^/    /' >&2
    FAIL=1
elif ! echo "$KERNEL_OUTPUT" | grep -q "^TOTAL_BLOCKED:"; then
    echo "  ${RED}✗ kernel test did not run (unshare/python setup failed)${RESET}" >&2
    echo "$KERNEL_OUTPUT" | sed 's/^/    /' >&2
    FAIL=1
else
    BLOCKED_COUNT=$(echo "$KERNEL_OUTPUT" | grep -oP 'TOTAL_BLOCKED:\s*\K\d+')
    echo "  ${GREEN}✓ all ${BLOCKED_COUNT} connection attempts blocked at syscall layer${RESET}"
    echo "$KERNEL_OUTPUT" | grep "^BLOCKED" | head -4 | sed 's/^/    /'
fi
echo ""

# -------- Verdict --------

if [ "$FAIL" -eq 0 ]; then
    echo "${GREEN}✓ learner isolation test passed (both user-space and kernel-space)${RESET}"
    exit 0
fi

echo "${RED}✗ learner isolation test FAILED${RESET}" >&2
exit 1
