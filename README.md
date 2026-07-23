# RGB Led Bar Replication for SteamOS

Replicate the Steam Machine's LED bar on an external WS2812/NeoPixel LED strip driven by an ESP8266, controlled by the Steam Game Mode LED customization menu.

Compatible with any Linux distribution running Steam in Game Mode (SteamOS, BazziteOS, CachyOS, ChimeraOS, HoloISO, etc.).

> **Note:** Only tested on SteamOS (Steam Machine). Other distros should work but are untested.

## What's included

| Path | Description |
|---|---|
| `leds-valve-shim/` | Kernel module source — creates `/dev/valve-leds-shim` to capture LED snapshots |
| `server/led_server.py` | TCP server that reads snapshots and broadcasts to connected ESP clients |
| `server/steamos-led.service` | Systemd service template |
| `firmware/esp8266-led-client.bin` | Pre-built ESP8266 firmware |
| `install.sh` | One-command installer for the kernel module + server + service |
| `flash-esp.sh` | One-command ESP8266 flasher |

## Requirements

### Server side (Linux PC)
- Any Linux distribution with **Steam in Game Mode** (SteamOS, BazziteOS, CachyOS, ChimeraOS, HoloISO, etc.)
- Desktop Mode access for installation
- Linux headers for your running kernel
- `make` and `gcc` (the installer handles dependencies automatically)

### Hardware (client side)
- ESP8266 (NodeMCU v2 or compatible)
- WS2812/NeoPixel LED strip (1–17 LEDs)
- USB cable for initial flashing

## Installation

### Step 1: Install the server (on the Linux PC)

```bash
git clone https://github.com/rpf16rj/steamos-led-bar-release.git
cd steamos-led-bar-release
sudo ./install.sh
```

The installer will:
1. Ask how many LEDs your bar has (1–17)
2. Ask the TCP port (default: 9876)
3. Build and install the `leds-valve-shim` kernel module
4. Install the LED server to `/opt/steamos-led-server/`
5. Enable and start the `steamos-led` systemd service

### Step 2: Flash the ESP8266

Connect the ESP8266 via USB, then:

```bash
./flash-esp.sh
```

> **Note:** You need `esptool` installed. On SteamOS:
> ```bash
> python3 -m venv ~/pio-env
> source ~/pio-env/bin/activate
> pip install esptool
> ```

### Step 3: Configure the ESP8266

After flashing, the ESP8266 creates a Wi-Fi access point:

- **SSID:** `Esp8266-RGB-Led`
- **IP:** `192.168.4.1`

Connect to it and open `http://192.168.4.1` to configure:
- Your Wi-Fi SSID and password
- LED server IP (your Steam Deck's IP) and port (default: 9876)
- Number of LEDs on your strip
- Optional static IP for the ESP

## Features

- **Full LED control** from the SteamOS Personalization menu
- **All effects supported:** static color, rainbow, breathing, patrol, factory, demo
- **Brightness control** works across all effects
- **LED remapping:** 17 source LEDs are averaged down to your strip size
- **Auto-reconnect:** ESP automatically reconnects if the server restarts
- **Web dashboard:** monitor connection status and test LEDs from the ESP's web UI

### Overlay features (v1.1.0)

Optional smart overlays that enhance the LED bar beyond Game Mode:

| Overlay | Flag | Description |
|---|---|---|
| **Temperature** | `--temp` | Full bar changes color by CPU/GPU temp: green (<65°C) → yellow → red (65–80°C) → red blinking (>80°C) |
| **Notifications** | `--notify` | Flash gold (achievements) or blue (messages) for 3.5s, then return to normal |
| **Audio reactive** | `--audio` | LED brightness pulses with system audio (PipeWire/PulseAudio, no microphone) |

Priority: Notification > Audio VU > Temperature > Game Mode base effect.

Below 65°C with no audio playing, Game Mode colors are shown as-is.

The installer asks which overlays to enable:
```
Enable temperature overlay? [Y/n]:
Enable notification overlay? [Y/n]:
Enable audio reactive overlay? [Y/n]:
```

To change overlays after installation, edit the service file:
```bash
sudo systemctl edit steamos-led --full
```
Add or remove `--temp`, `--notify`, `--audio` from the `ExecStart=` line, then:
```bash
sudo systemctl daemon-reload && sudo systemctl restart steamos-led
```

## Wiring

### Power supply

```text
USB cable ──→ ESP8266 (powered via USB)
                 |
                 +── VV (5V pin) ──→ LED strip VCC
                 +── GND ──────────→ LED strip GND
```

> For strips with more than 8 LEDs, consider an external 5V supply connected directly to the strip VCC/GND (sharing GND with the ESP).

### LED data path — Option A: Level shifter (74AHCT125)

```text
ESP8266 GPIO14 (D5) ───→ 74AHCT125 1A (pin 2)
74AHCT125 /1OE (pin 1) ─→ GND
74AHCT125 VCC (pin 14) ──→ 5 V
74AHCT125 GND (pin 7) ───→ GND
74AHCT125 1Y (pin 3) ────→ 330 Ω resistor ──→ WS2812B DIN
```

### LED data path — Option B: Diode (simpler, recommended)

A signal diode (e.g. 1N4148) can be used instead of the level shifter. The WS2812B typically accepts 3.3V logic when VCC is 5V, especially with short wire runs.

```text
ESP8266 GPIO14 (D5) ───→ Diode (anode) ──→ (cathode) ──→ WS2812B DIN
```

No 330Ω resistor needed with this method. The diode provides basic protection against back-feeding.

### Summary table

| ESP8266 Pin | Connection |
|---|---|
| D5 (GPIO14) | LED strip data (via shifter or diode) |
| GND | LED strip GND |
| VV (5V) | LED strip VCC |

### Optional

- **1000 µF capacitor** between WS2812B VCC and GND, close to the first LED (recommended for longer strips)

## Troubleshooting

| Problem | Solution |
|---|---|
| LEDs don't light up | Check `sudo systemctl status steamos-led` and ESP serial log |
| Module build fails | Install headers: `sudo pacman -S linux-neptune-headers base-devel` |
| Permission denied on `/dev/ttyUSB0` | `sudo chmod 666 /dev/ttyUSB0` or add user to `dialout` group |
| ESP can't connect to server | Make sure the SteamOS machine and ESP are on the same network |
| Effects don't change | Ensure you're in Game Mode (Desktop Mode has limited LED control) |
| LEDs very dim | WS2812B on short runs may work with 3.3V data but dim — try the diode or level shifter |

## Uninstall

```bash
sudo ./uninstall.sh
```

The script handles the SteamOS read-only filesystem automatically (disables it, removes files, re-enables it).

## Support

If you find this project useful, consider buying me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/rpf16rj)

## License

- Kernel module (`leds-valve-shim`): GPL v2
- Server and ESP firmware: MIT
