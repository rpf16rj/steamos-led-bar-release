# Changelog

## v1.1.2

### Fixed
- Patrol effect now uses subpixel interpolation for smooth movement between LEDs
- Patrol no longer pauses on duplicated positions at either end of the strip
- Animated effects now render exclusively on a stable 50 FPS scheduler instead of receiving irregular extra frames from TCP snapshots
- Effect frame timing compensates for loop jitter without accumulating drift
- Release workflow now uses only the matching version section from `CHANGELOG.md` instead of repeating a fixed body
- Release workflow validates that the pushed tag has a corresponding changelog entry
- Updated `actions/checkout` to v5 to remove the Node.js 20 deprecation warning

## v1.1.1

### Fixed
- Audio VU now waits for the user PipeWire session after boot instead of disabling itself permanently
- Audio capture automatically reconnects if `pw-record` or the default audio sink becomes unavailable
- Notification overlay now waits for and reconnects to the user session DBus after boot
- Audio level and peak state reset cleanly while capture is reconnecting

## v1.1.0

### Added
- **Temperature overlay** — Full LED bar changes color based on CPU/GPU temperature
  - Below 65°C: Game Mode colors prevail (no overlay)
  - Yellow to red gradient: 65–80°C
  - Red blinking: above 80°C
- **Notification overlay** — Flash on Steam achievements (gold) and messages (blue) for 3.5 seconds via DBus
- **Audio reactive overlay (VU meter)** — LEDs fill left-to-right with green→yellow→red gradient based on system audio level (PipeWire, no microphone needed)
- Overlay priority system: Notification > Audio VU > Temperature > Game Mode
- When audio and temperature (≥65°C) are both active, alternates between them every 10 seconds
- New CLI flags: `--temp`, `--notify`, `--audio`
- Install script now asks which overlays to enable

### Changed
- `led_server.py` refactored with threading-based overlay architecture
- Audio capture uses `pw-record` with `stream.capture.sink=true` (native PipeWire)
- Service runs as user `deck` with PipeWire/DBus session access
- Overlays force `effect=MANUAL` in snapshot header so ESP renders raw pixels
- Service template updated with overlay placeholder

### Fixed (ESP8266 firmware)
- **Wi-Fi auto-reconnect** — checks every 10s, reconnects automatically if Wi-Fi drops
- **TCP watchdog** — if no data received for 30s, disconnects and retries TCP connection
- **Wi-Fi sleep disabled** — ensures reliable TCP streaming (modem sleep caused packet loss)

### Fixed (LED server)
- Server now sends keepalive frames every 5s to prevent ESP TCP watchdog from firing
- Client sockets use blocking mode with timeout instead of non-blocking (fixes send errors)
- TCP_NODELAY enabled for lower latency LED updates
- VU meter direction corrected (fills right→left: green→yellow→red)
- Temperature overlay now uses only last 2 LEDs permanently (no more alternating)
- VU meter area shrinks proportionally when temperature LEDs are active
- Game Mode brightness_scale is always respected by overlays
- Smooth 300ms crossfade transition when switching between modes (VU start/stop, temp on/off)

## v1.0.0

### Initial release
- Kernel module `leds-valve-shim` — captures LED state from Game Mode
- TCP LED server with 17→N LED remapping
- Pre-built ESP8266 firmware with all effects (rainbow, breath, patrol, factory, demo)
- Automated install script with dependency management (SteamOS, Arch, Debian, Fedora)
- Automated flash script for ESP8266 (auto-installs esptool)
- Uninstall script with SteamOS read-only filesystem support
- Wiring documentation with diode alternative
