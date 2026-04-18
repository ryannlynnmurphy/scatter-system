#!/usr/bin/env bash
# test_leak_free.sh — architectural enforcement of the single-path claim.
#
# Claim: every external network call in the distilled Scatter system goes
# through scatter/api.py. Claim does not extend to phase-one scaffolding
# (scatter-ops, scatter-data, scatter-journal, scatter-code) which is
# pending retirement under task #28.
#
# Rule: any Python file under scatter/ (the new architecture) that imports
# urllib / requests / httpx / socket must be in the allowlist.
#
# Exit 0 if all imports accounted for. Exit 1 if there is an unaccounted
# import — that is a leak and must be routed through scatter/api.py.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Strict-architecture allowlist — files we intend to permit. Each has a
# documented reason in the comment. Anything NOT on this list that
# imports network modules is a leak.
declare -A ALLOWED
ALLOWED["scatter/api.py"]="vetted external-call path, audit-logged"
ALLOWED["scatter/server.py"]="localhost Ollama only (127.0.0.1:11434)"
ALLOWED["scatter/launcher.py"]="localhost /health polling for the native window"
ALLOWED["scatter/ai_local.py"]="localhost Ollama only, local whisper subprocess"
ALLOWED["scatter/teaching.py"]="phase-one pedagogy, LEGACY pending retirement (task #28)"
# scatter_core.py is NOT on this list — it must not import network modules.

PATTERN='^[[:space:]]*(from[[:space:]]+(urllib|urllib\.[a-z]+)[[:space:]]+import|import[[:space:]]+(urllib|requests|httpx|socket)([[:space:]]|$))'

# Scan: only .py files under scatter/ and scatter_core.py. Phase-one
# directories (scatter-code, scatter-data, scatter-journal, scatter-ops)
# are out of scope until task #28.
MATCHES=$(grep -lrE "$PATTERN" --include="*.py" \
    scatter/ scatter_core.py 2>/dev/null || true)

VIOLATIONS=()
for file in $MATCHES; do
    rel="${file#./}"
    if [[ -v "ALLOWED[$rel]" ]]; then
        continue
    fi
    VIOLATIONS+=("$rel")
done

if [ ${#VIOLATIONS[@]} -eq 0 ]; then
    echo "✓ leak test passed — every network import is on the allowlist"
    echo ""
    echo "allowlist (intentional permissions):"
    for file in "${!ALLOWED[@]}"; do
        printf "  %-30s — %s\n" "$file" "${ALLOWED[$file]}"
    done
    exit 0
fi

echo "✗ LEAK TEST FAILED" >&2
echo "" >&2
echo "Unauthorized files import network modules:" >&2
for v in "${VIOLATIONS[@]}"; do
    echo "  $v:" >&2
    grep -nE "$PATTERN" "$v" | head -3 | sed 's/^/      /' >&2
done
echo "" >&2
echo "Every external call must route through scatter/api.py." >&2
echo "If an allowlist addition is legitimate, update ALLOWED in $0" >&2
echo "and document the reason. If you are making an external call," >&2
echo "add it as an adapter in scatter/api.py instead." >&2
exit 1
