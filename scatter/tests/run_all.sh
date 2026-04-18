#!/usr/bin/env bash
# Run all Scatter architectural tests. Any failure aborts.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Scatter architectural tests"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "▸ syntax check (all *.py under scatter/ and scatter_core.py)"
cd "$HERE/../.."
find scatter/ -name '*.py' -type f -print0 | while IFS= read -r -d '' f; do
    python3 -c "import ast; ast.parse(open('$f').read())" || { echo "  ✗ syntax error: $f" >&2; exit 1; }
done
python3 -c "import ast; ast.parse(open('scatter_core.py').read())"
echo "  ✓ syntax ok"
echo ""

echo "▸ leak test"
bash "$HERE/test_leak_free.sh"
echo ""

echo "▸ api middleware self-check"
python3 "$HERE/../api.py" --self-check
echo ""

echo "▸ learner-profile kernel isolation (unshare --user --net)"
bash "$HERE/test_learner_isolated.sh"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  all tests passed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
