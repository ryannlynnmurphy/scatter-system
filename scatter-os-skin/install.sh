#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Scatter OS skin — runs once with sudo. Installs:
#   • Plymouth boot theme
#   • GRUB menu theme
#   • /etc/issue + /etc/motd
#   • (optional) hostname = scatter
# Everything above app-chrome (GTK, icons, wallpaper, terminal, Firefox) is
# installed in user-space and does NOT need this script.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Scatter OS skin: run me with sudo."
    echo "  sudo bash $0 $*"
    exit 1
fi

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SET_HOSTNAME=0
for arg in "$@"; do
    case "$arg" in
        --hostname) SET_HOSTNAME=1 ;;
    esac
done

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  SCATTER — installing the OS skin                ║"
echo "  ║  the alignment OS • small tech • local • yours   ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Plymouth ──────────────────────────────────────────────────────────
PLY_SRC="$HERE/plymouth"
PLY_DST="/usr/share/plymouth/themes/scatter"
echo "[1/4] Plymouth boot theme → $PLY_DST"
mkdir -p "$PLY_DST"
cp -f "$PLY_SRC/scatter.plymouth" "$PLY_DST/"
cp -f "$PLY_SRC/scatter.script"   "$PLY_DST/"
cp -f "$PLY_SRC/background.png"   "$PLY_DST/"
cp -f "$PLY_SRC/logo.png"         "$PLY_DST/"
cp -f "$PLY_SRC/dot.png"          "$PLY_DST/"
cp -f "$PLY_SRC/dot-amber.png"    "$PLY_DST/"

if command -v update-alternatives >/dev/null 2>&1; then
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
        default.plymouth "$PLY_DST/scatter.plymouth" 200 >/dev/null
    update-alternatives --set default.plymouth "$PLY_DST/scatter.plymouth"
fi
if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -u
fi

# ── GRUB ──────────────────────────────────────────────────────────────
GRUB_SRC="$HERE/grub"
GRUB_DST="/boot/grub/themes/scatter"
echo "[2/4] GRUB menu theme → $GRUB_DST"
mkdir -p "$GRUB_DST"
cp -f "$GRUB_SRC/theme.txt"      "$GRUB_DST/"
cp -f "$GRUB_SRC/background.png" "$GRUB_DST/"
cp -f "$GRUB_SRC/select_bg.png"  "$GRUB_DST/"

if ! grep -q "^GRUB_THEME=" /etc/default/grub; then
    echo "GRUB_THEME=\"$GRUB_DST/theme.txt\"" >> /etc/default/grub
else
    sed -i "s|^GRUB_THEME=.*|GRUB_THEME=\"$GRUB_DST/theme.txt\"|" /etc/default/grub
fi
if ! grep -q "^GRUB_BACKGROUND=" /etc/default/grub; then
    echo "GRUB_BACKGROUND=\"$GRUB_DST/background.png\"" >> /etc/default/grub
else
    sed -i "s|^GRUB_BACKGROUND=.*|GRUB_BACKGROUND=\"$GRUB_DST/background.png\"|" /etc/default/grub
fi
# Drop the Ubuntu splash on boot (show our plymouth instead of ubuntu_logo)
sed -i 's|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"|' /etc/default/grub
if command -v update-grub >/dev/null 2>&1; then
    update-grub
fi

# ── /etc/issue + /etc/motd ────────────────────────────────────────────
echo "[3/5] /etc/issue + /etc/motd"
[ -f /etc/issue ] && [ ! -f /etc/issue.scatter-backup ] && cp /etc/issue /etc/issue.scatter-backup
[ -f /etc/motd ]  && [ ! -f /etc/motd.scatter-backup  ] && cp /etc/motd  /etc/motd.scatter-backup
cp -f "$HERE/etc/issue" /etc/issue
cp -f "$HERE/etc/motd"  /etc/motd

# ── hostname ──────────────────────────────────────────────────────────
if [ "$SET_HOSTNAME" -eq 1 ]; then
    echo "[4/5] hostname → scatter"
    hostnamectl set-hostname scatter
    # Keep /etc/hosts consistent so sudo doesn't warn
    if ! grep -q "127.0.1.1.*scatter" /etc/hosts; then
        if grep -q "^127.0.1.1" /etc/hosts; then
            sed -i 's|^127.0.1.1.*|127.0.1.1\tscatter|' /etc/hosts
        else
            echo -e "127.0.1.1\tscatter" >> /etc/hosts
        fi
    fi
else
    echo "[4/5] hostname: skipped (pass --hostname to set it to 'scatter')"
fi

# ── OS identity (os-release, lsb-release, issue.net, grub distributor) ─
# Same pattern Pop!_OS / Zorin / SteamOS use: own NAME/ID, keep ID_LIKE
# so apt/snap/third-party installers still recognize the Ubuntu base.
echo "[5/5] OS identity → Scatter OS"

[ -f /etc/os-release ]  && [ ! -f /etc/os-release.scatter-backup ]  && cp /etc/os-release  /etc/os-release.scatter-backup
[ -f /etc/lsb-release ] && [ ! -f /etc/lsb-release.scatter-backup ] && cp /etc/lsb-release /etc/lsb-release.scatter-backup
[ -f /etc/issue.net ]   && [ ! -f /etc/issue.net.scatter-backup ]   && cp /etc/issue.net   /etc/issue.net.scatter-backup

# Read VERSION_ID / VERSION_CODENAME / UBUNTU_CODENAME from the current
# os-release so upgrades don't strand us on a stale version string.
UBU_VERSION_ID="$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID:-24.04}")"
UBU_CODENAME="$(. /etc/os-release 2>/dev/null; echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-noble}}")"

cat > /etc/os-release <<EOF
PRETTY_NAME="Scatter OS"
NAME="Scatter OS"
VERSION_ID="$UBU_VERSION_ID"
VERSION="$UBU_VERSION_ID ($UBU_CODENAME)"
VERSION_CODENAME=$UBU_CODENAME
ID=scatter
ID_LIKE="ubuntu debian"
HOME_URL="https://scatter.computer/"
SUPPORT_URL="https://scatter.computer/"
BUG_REPORT_URL="https://scatter.computer/"
PRIVACY_POLICY_URL="https://scatter.computer/"
UBUNTU_CODENAME=$UBU_CODENAME
LOGO=scatter
EOF
ln -sf /etc/os-release /usr/lib/os-release 2>/dev/null || true

cat > /etc/lsb-release <<EOF
DISTRIB_ID=Scatter
DISTRIB_RELEASE=$UBU_VERSION_ID
DISTRIB_CODENAME=$UBU_CODENAME
DISTRIB_DESCRIPTION="Scatter OS"
EOF

echo "Scatter OS \\n \\l" > /etc/issue.net

# GRUB distributor — hard-code so `Advanced options for Ubuntu` becomes Scatter
if grep -q "^GRUB_DISTRIBUTOR=" /etc/default/grub; then
    sed -i 's|^GRUB_DISTRIBUTOR=.*|GRUB_DISTRIBUTOR="Scatter"|' /etc/default/grub
else
    echo 'GRUB_DISTRIBUTOR="Scatter"' >> /etc/default/grub
fi
if command -v update-grub >/dev/null 2>&1; then
    update-grub
fi

echo ""
echo "  done. reboot to see it:"
echo "    sudo reboot"
echo ""
