#!/usr/bin/env bash
# One-shot filesystem migration: legacy hazel/hzl/HZL paths → scatter naming.
set -euo pipefail
log() { printf '%s\n' "$*"; }
H="${HOME:?}"
if [[ -d "$H/projects/hazel" && ! -e "$H/projects/scatter" ]]; then
  mv "$H/projects/hazel" "$H/projects/scatter"
  log "Renamed ~/projects/hazel → ~/projects/scatter"
elif [[ -d "$H/projects/scatter" ]]; then
  log "OK: ~/projects/scatter already exists"
else
  log "Skip: ~/projects/hazel not found"
fi
SCATTER_ROOT="$H/projects/scatter"
if [[ ! -d "$SCATTER_ROOT" ]]; then
  log "Nothing else to do (no scatter projects root)."
  exit 0
fi
cd "$SCATTER_ROOT"
for old in hzl-music hzl-write hzl-draft hzl-film hzl-studio-os hzl-stream; do
  new="${old/hzl-/scatter-}"
  if [[ -d "$old" && ! -e "$new" ]]; then
    mv "$old" "$new"
    log "Renamed $old → $new"
  fi
done
if [[ -d "$H/HZL-Academy-" && ! -e "$H/scatter-academy" ]]; then
  mv "$H/HZL-Academy-" "$H/scatter-academy"
  log "Renamed ~/HZL-Academy- → ~/scatter-academy"
elif [[ -d "$H/scatter-academy" ]]; then
  log "OK: ~/scatter-academy already exists"
fi
log "Done."
