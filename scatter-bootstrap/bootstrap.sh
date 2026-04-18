#!/usr/bin/env bash
# scatter-bootstrap.sh — turn a fresh Ubuntu 24.04 LTS into a Scatter machine.
#
# Idempotent. Rerunnable. Non-destructive by default.
#
# Modes:
#   (default)       dry-run. Print what each phase would do. Execute nothing.
#   --apply         run non-sudo phases. Writes to your home directory only.
#   --apply-sudo    additionally run sudo phases (prompts for confirmation
#                   at each sudo phase — you approve one at a time).
#
# Options:
#   --profile researcher|learner   which profile to configure (default: researcher)
#   --skip <n>                     skip phase number n (can repeat)
#   --only <n>                     run only phase n (can repeat)
#   --help                         print this help
#
# Ubuntu substrate named: 24.04 LTS "Noble Numbat". When 26.04 ships,
# this script needs re-certification — some phases (Plymouth, GDM) have
# version-specific paths.

set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
SCATTER_HOME="$(cd "$ROOT/.." && pwd)"
export SCATTER_HOME

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
DIM=$'\033[2m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

APPLY=0
APPLY_SUDO=0
PROFILE="researcher"
SKIP=()
ONLY=()

while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --apply-sudo) APPLY=1; APPLY_SUDO=1 ;;
        --profile) shift; PROFILE="$1" ;;
        --skip) shift; SKIP+=("$1") ;;
        --only) shift; ONLY+=("$1") ;;
        --help|-h)
            sed -n '2,25p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ "$PROFILE" != "researcher" ] && [ "$PROFILE" != "learner" ]; then
    echo "${RED}✗ invalid profile: $PROFILE (must be researcher or learner)${RESET}" >&2
    exit 2
fi

echo ""
echo "${BOLD}Scatter bootstrap${RESET}"
echo "${DIM}substrate: Ubuntu 24.04 LTS${RESET}"
echo "${DIM}profile:   $PROFILE${RESET}"
if [ "$APPLY" -eq 0 ]; then
    mode_txt="${YELLOW}dry-run (pass --apply to execute)${RESET}"
elif [ "$APPLY_SUDO" -eq 0 ]; then
    mode_txt="${GREEN}apply non-sudo phases${RESET}"
else
    mode_txt="${GREEN}apply non-sudo + sudo phases (per-phase confirmation)${RESET}"
fi
echo "${DIM}mode:      $mode_txt${RESET}"
echo ""

PHASES=(
    "01-substrate.sh"
    "02-commons-wrap.sh"
    "03-prototypes-wrap.sh"
    "04-deps-apt.sh"
    "05-hostname.sh"
    "06-os-release.sh"
    "07-plymouth.sh"
    "08-welcome.sh"
    "09-grub.sh"
    "10-gdm.sh"
)

# in_array helper
contains() {
    local needle="$1"; shift
    for item in "$@"; do [ "$item" = "$needle" ] && return 0; done
    return 1
}

for phase_file in "${PHASES[@]}"; do
    num="${phase_file:0:2}"
    # skip/only filters
    if [ "${#SKIP[@]}" -gt 0 ] && contains "$num" "${SKIP[@]}"; then
        echo "${DIM}▸ phase $num skipped (--skip)${RESET}"
        continue
    fi
    if [ "${#ONLY[@]}" -gt 0 ] && ! contains "$num" "${ONLY[@]}"; then
        continue
    fi

    phase_path="$ROOT/phases/$phase_file"
    if [ ! -x "$phase_path" ]; then
        echo "${RED}✗ phase $phase_file not executable${RESET}" >&2
        exit 1
    fi

    echo "${BOLD}▸ phase $phase_file${RESET}"
    export SCATTER_APPLY="$APPLY"
    export SCATTER_APPLY_SUDO="$APPLY_SUDO"
    export SCATTER_PROFILE="$PROFILE"
    "$phase_path" || {
        echo "${RED}✗ phase $phase_file failed${RESET}" >&2
        exit 1
    }
    echo ""
done

echo "${GREEN}${BOLD}bootstrap complete${RESET}"
if [ "$APPLY" -eq 0 ]; then
    echo "${DIM}That was a dry-run. Rerun with --apply to actually execute non-sudo phases.${RESET}"
fi
if [ "$APPLY" -eq 1 ] && [ "$APPLY_SUDO" -eq 0 ]; then
    echo "${DIM}Sudo phases (hostname, os-release, plymouth) were not touched. Rerun with --apply-sudo to go deeper — you'll be asked to confirm each one.${RESET}"
fi
echo ""
