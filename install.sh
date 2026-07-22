#!/bin/bash
# RGB Led Bar Replication for SteamOS — Installer
# Installs leds-valve-shim kernel module + LED server + systemd service.
# Run as: sudo ./install.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SHIM_DIR="$HERE/leds-valve-shim"
SERVER_DIR="$HERE/server"
SERVICE_NAME="steamos-led"
SERVER_INSTALL_DIR="/opt/steamos-led-server"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REL=$(uname -r)

[ "$(id -u)" = 0 ] || { echo "❌ Run with sudo: sudo ./install.sh"; exit 1; }

# ── Detect distro ─────────────────────────────────────────────
DISTRO="unknown"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        steamos|holo) DISTRO="steamos" ;;
        arch|manjaro|endeavouros|garuda|cachyos) DISTRO="arch" ;;
        ubuntu|debian|linuxmint|pop) DISTRO="debian" ;;
        fedora|nobara|bazzite) DISTRO="fedora" ;;
        *) DISTRO="$ID" ;;
    esac
fi
echo "→ Detected distro: $DISTRO"

# ── SteamOS read-only rootfs ───────────────────────────────────
ROOTFS_WAS_READONLY=0
restore_readonly() {
    if [ "$ROOTFS_WAS_READONLY" = 1 ]; then
        if command -v steamos-readonly >/dev/null 2>&1; then
            steamos-readonly enable || true
        fi
    fi
}
trap restore_readonly EXIT

if command -v steamos-readonly >/dev/null 2>&1; then
    if steamos-readonly status 2>/dev/null | grep -qi enabled; then
        steamos-readonly disable
        ROOTFS_WAS_READONLY=1
    fi
fi

# ── Install build dependencies ─────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  Step 0: Installing dependencies"
echo "══════════════════════════════════════════════"

install_deps_arch() {
    local NEEDED=()
    command -v make >/dev/null 2>&1 || NEEDED+=(make)
    command -v gcc >/dev/null 2>&1 || NEEDED+=(gcc)
    [ -d "/usr/lib/modules/$REL/build" ] || NEEDED+=(linux-headers)
    if [ ${#NEEDED[@]} -gt 0 ]; then
        echo "→ Installing: ${NEEDED[*]}"
        pacman -Sy --noconfirm --needed base-devel "${NEEDED[@]}" 2>/dev/null || \
        pacman -Sy --noconfirm --needed "${NEEDED[@]}"
    else
        echo "→ All build dependencies already installed"
    fi
}

install_deps_debian() {
    local NEEDED=()
    command -v make >/dev/null 2>&1 || NEEDED+=(build-essential)
    command -v gcc >/dev/null 2>&1 || NEEDED+=(build-essential)
    [ -d "/usr/lib/modules/$REL/build" ] || NEEDED+=("linux-headers-$REL")
    if [ ${#NEEDED[@]} -gt 0 ]; then
        echo "→ Installing: ${NEEDED[*]}"
        apt-get update -qq
        apt-get install -y "${NEEDED[@]}"
    else
        echo "→ All build dependencies already installed"
    fi
}

install_deps_fedora() {
    local NEEDED=()
    command -v make >/dev/null 2>&1 || NEEDED+=(make)
    command -v gcc >/dev/null 2>&1 || NEEDED+=(gcc)
    [ -d "/usr/lib/modules/$REL/build" ] || NEEDED+=("kernel-devel-$REL")
    if [ ${#NEEDED[@]} -gt 0 ]; then
        echo "→ Installing: ${NEEDED[*]}"
        dnf install -y "${NEEDED[@]}"
    else
        echo "→ All build dependencies already installed"
    fi
}

case "$DISTRO" in
    steamos|arch)
        install_deps_arch ;;
    debian)
        install_deps_debian ;;
    fedora)
        install_deps_fedora ;;
    *)
        echo "⚠️  Unknown distro '$DISTRO'. Please ensure you have:"
        echo "    - make, gcc"
        echo "    - linux headers for kernel $REL"
        echo "   installed before continuing."
        read -rp "Continue anyway? [y/N]: " CONT
        [[ "${CONT,,}" == "y" ]] || exit 1
        ;;
esac

# ── Prompt for number of LEDs ──────────────────────────────────
read -rp "How many LEDs does your bar have? [8]: " NUM_LEDS
NUM_LEDS=${NUM_LEDS:-8}
if ! [[ "$NUM_LEDS" =~ ^[0-9]+$ ]] || [ "$NUM_LEDS" -lt 1 ] || [ "$NUM_LEDS" -gt 17 ]; then
    echo "❌ Invalid number of LEDs (must be 1-17)"
    exit 1
fi
echo "→ Configuring for $NUM_LEDS LEDs"

# ── Prompt for TCP port ────────────────────────────────────────
read -rp "Server TCP port? [9876]: " PORT
PORT=${PORT:-9876}
echo "→ Using port $PORT"

# ── 1. Install kernel module ──────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  Step 1: Kernel module (leds-valve-shim)"
echo "══════════════════════════════════════════════"

if [ -f "$SHIM_DIR/install.sh" ]; then
    bash "$SHIM_DIR/install.sh"
else
    echo "❌ leds-valve-shim/install.sh not found"
    exit 1
fi

# ── 2. Install LED server ─────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  Step 2: LED server"
echo "══════════════════════════════════════════════"

mkdir -p "$SERVER_INSTALL_DIR"
install -m755 "$SERVER_DIR/led_server.py" "$SERVER_INSTALL_DIR/led_server.py"
echo "→ Installed led_server.py to $SERVER_INSTALL_DIR"

# ── 3. Install systemd service ────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  Step 3: Systemd service"
echo "══════════════════════════════════════════════"

# Stop existing service if running.
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

# Generate service file with user settings.
sed -e "s/__NUM_LEDS__/$NUM_LEDS/g" \
    -e "s/--port 9876/--port $PORT/g" \
    "$SERVER_DIR/steamos-led.service" > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

echo "→ Service $SERVICE_NAME enabled and started"

# ── Done ───────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  ✅ Installation complete!"
echo "══════════════════════════════════════════════"
echo ""
echo "  Kernel module: leds-valve-shim (loaded)"
echo "  Server:        $SERVER_INSTALL_DIR/led_server.py"
echo "  Service:       $SERVICE_NAME (running)"
echo "  Output LEDs:   $NUM_LEDS"
echo "  TCP port:      $PORT"
echo ""
echo "  Check status:  sudo systemctl status $SERVICE_NAME"
echo "  View logs:     sudo journalctl -u $SERVICE_NAME -f"
echo ""

# ── Offer to flash ESP8266 ─────────────────────────────────────
read -rp "Flash ESP8266 firmware now? (connect it via USB first) [y/N]: " FLASH_NOW
if [[ "${FLASH_NOW,,}" == "y" || "${FLASH_NOW,,}" == "yes" ]]; then
    # Drop privileges for flash (esptool doesn't need root)
    FLASH_SCRIPT="$HERE/flash-esp.sh"
    if [ -f "$FLASH_SCRIPT" ]; then
        bash "$FLASH_SCRIPT"
    else
        echo "❌ flash-esp.sh not found at $FLASH_SCRIPT"
    fi
fi
