#!/bin/bash
# RGB Led Bar Replication for SteamOS — ESP8266 Flasher
# Flashes the pre-built firmware to an ESP8266 via USB.
# Run as: ./flash-esp.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
FW="$HERE/firmware/esp8266-led-client.bin"

if [ ! -f "$FW" ]; then
    echo "❌ Firmware not found: $FW"
    exit 1
fi

# ── Detect serial port ────────────────────────────────────────
PORTS=( $(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true) )
if [ ${#PORTS[@]} -eq 0 ]; then
    echo "❌ No serial port found. Connect the ESP8266 via USB."
    exit 1
elif [ ${#PORTS[@]} -eq 1 ]; then
    PORT="${PORTS[0]}"
    echo "→ Found serial port: $PORT"
else
    echo "Multiple serial ports found:"
    for i in "${!PORTS[@]}"; do
        echo "  $((i+1))) ${PORTS[$i]}"
    done
    read -rp "Select port number [1]: " SEL
    SEL=${SEL:-1}
    PORT="${PORTS[$((SEL-1))]}"
fi

# ── Find or setup esptool ─────────────────────────────────────
VENV_DIR="$HOME/.steamos-led-flash-env"
ESPTOOL=""

# 1. Check if esptool is available system-wide
if command -v esptool.py >/dev/null 2>&1; then
    ESPTOOL="esptool.py"
elif command -v esptool >/dev/null 2>&1; then
    ESPTOOL="esptool"
fi

# 2. Check existing venvs (pio-env or our own)
if [ -z "$ESPTOOL" ]; then
    for VENV in "$HOME/pio-env" "$VENV_DIR"; do
        if [ -f "$VENV/bin/esptool.py" ]; then
            ESPTOOL="$VENV/bin/esptool.py"
            break
        elif [ -f "$VENV/bin/python3" ] && "$VENV/bin/python3" -c "import esptool" 2>/dev/null; then
            ESPTOOL="$VENV/bin/python3 -m esptool"
            break
        fi
    done
fi

# 3. If still not found, create a venv and install esptool
if [ -z "$ESPTOOL" ]; then
    echo ""
    echo "→ esptool not found. Setting up automatically..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet esptool
    if [ -f "$VENV_DIR/bin/esptool.py" ]; then
        ESPTOOL="$VENV_DIR/bin/esptool.py"
    else
        ESPTOOL="$VENV_DIR/bin/python3 -m esptool"
    fi
    echo "→ esptool installed in $VENV_DIR"
fi

if [ -z "$ESPTOOL" ]; then
    echo "❌ Failed to setup esptool."
    exit 1
fi

# ── Flash ─────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════"
echo "  Flashing ESP8266"
echo "══════════════════════════════════════════════"
echo "  Firmware: $FW"
echo "  Port:     $PORT"
echo ""

$ESPTOOL --chip esp8266 \
    --port "$PORT" \
    --baud 921600 \
    write_flash \
    --flash_mode dio \
    --flash_size detect \
    0x0 "$FW"

echo ""
echo "══════════════════════════════════════════════"
echo "  ✅ Flash complete!"
echo "══════════════════════════════════════════════"
echo ""
echo "  The ESP8266 will reboot and start an AP:"
echo "    SSID: Esp8266-RGB-Led"
echo "    IP:   192.168.4.1"
echo ""
echo "  Connect to the AP and open http://192.168.4.1"
echo "  to configure Wi-Fi and LED server settings."
echo ""
