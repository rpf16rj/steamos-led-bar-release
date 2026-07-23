#!/usr/bin/env python3
"""Forward 100-byte VLED snapshots from /dev/valve-leds-shim to TCP clients.

Supports overlay layers:
  - Temperature: full-bar color based on CPU/GPU temp
  - Notifications: flash on Steam achievements/messages via DBus
  - Audio reactive: modulate brightness with system audio via PipeWire/PulseAudio
"""

import argparse
import glob
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time

SNAPSHOT_SIZE = 100
SRC_NUM_LEDS = 17
PIXELS_OFFSET = 32
PIXEL_SIZE = 4
DEFAULT_DEVICE = "/dev/valve-leds-shim"
DEFAULT_PORT = 9876
DEFAULT_LEDS = 17
POLL_INTERVAL = 0.05  # seconds between device reads

clients = []
latest = None
running = True
num_output_leds = DEFAULT_LEDS

# ── Overlay state ──────────────────────────────────────────────
overlay_lock = threading.Lock()

# Temperature overlay
temp_overlay_enabled = False
temp_color = None  # (r, g, b) or None
temp_blink = False
temp_blink_state = True
temp_last_read = 0.0
temp_current = 0.0  # current temperature
TEMP_READ_INTERVAL = 2.0  # read every 2s
TEMP_THRESHOLD_WARM = 65
TEMP_THRESHOLD_HOT = 80
TEMP_SHOW_CYCLE = 10.0  # alternate temp/audio every 10s

# Notification overlay
notif_overlay_enabled = False
notif_active = False
notif_color = (255, 215, 0)  # gold for achievements
notif_end_time = 0.0
NOTIF_DURATION = 3.5  # seconds

# Audio overlay (VU meter)
audio_overlay_enabled = False
audio_level = 0.0  # 0.0 to 1.0
audio_peak = 0.0  # peak hold for VU
audio_process = None


# ══════════════════════════════════════════════════════════════════
# Network helpers
# ══════════════════════════════════════════════════════════════════

def remove_client(sock):
    try:
        sock.close()
    except Exception:
        pass
    if sock in clients:
        clients.remove(sock)


def broadcast(snapshot):
    dead = []
    for c in clients:
        try:
            c.sendall(snapshot)
        except (BrokenPipeError, OSError):
            dead.append(c)
    for c in dead:
        remove_client(c)


def accept_client(server):
    conn, addr = server.accept()
    print(f"client connected: {addr}", file=sys.stderr)
    conn.setblocking(False)
    if latest:
        try:
            conn.sendall(latest)
        except (BrokenPipeError, OSError):
            conn.close()
            return
    clients.append(conn)


# ══════════════════════════════════════════════════════════════════
# Snapshot processing
# ══════════════════════════════════════════════════════════════════

def read_snapshot(led_fd):
    data = os.read(led_fd, SNAPSHOT_SIZE)
    if len(data) != SNAPSHOT_SIZE:
        print(f"short read from LED device: {len(data)} bytes", file=sys.stderr)
        return None
    return data


def remap_snapshot(data, out_leds):
    """Remap 17 source LEDs to out_leds by averaging pixel blocks."""
    if out_leds >= SRC_NUM_LEDS:
        return data

    header = bytearray(data[:PIXELS_OFFSET])
    pixels_out = bytearray(out_leds * PIXEL_SIZE)

    for i in range(out_leds):
        start = i * SRC_NUM_LEDS / out_leds
        end = (i + 1) * SRC_NUM_LEDS / out_leds

        r_sum, g_sum, b_sum, br_sum = 0.0, 0.0, 0.0, 0.0
        weight_total = 0.0

        j = int(start)
        while j < end and j < SRC_NUM_LEDS:
            lo = max(start, j)
            hi = min(end, j + 1)
            w = hi - lo

            off = PIXELS_OFFSET + j * PIXEL_SIZE
            r_sum += data[off + 0] * w
            g_sum += data[off + 1] * w
            b_sum += data[off + 2] * w
            br_sum += data[off + 3] * w
            weight_total += w
            j += 1

        if weight_total > 0:
            pixels_out[i * PIXEL_SIZE + 0] = int(r_sum / weight_total + 0.5)
            pixels_out[i * PIXEL_SIZE + 1] = int(g_sum / weight_total + 0.5)
            pixels_out[i * PIXEL_SIZE + 2] = int(b_sum / weight_total + 0.5)
            pixels_out[i * PIXEL_SIZE + 3] = int(br_sum / weight_total + 0.5)

    padding = bytearray((SRC_NUM_LEDS - out_leds) * PIXEL_SIZE)
    return bytes(header + pixels_out + padding)


# ══════════════════════════════════════════════════════════════════
# Temperature overlay
# ══════════════════════════════════════════════════════════════════

def get_max_temperature():
    """Read max temperature from thermal zones and GPU."""
    temps = []

    # CPU thermal zones
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(path) as f:
                temps.append(int(f.read().strip()) / 1000.0)
        except (OSError, ValueError):
            pass

    # AMD GPU (amdgpu)
    for path in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input"):
        try:
            with open(path) as f:
                temps.append(int(f.read().strip()) / 1000.0)
        except (OSError, ValueError):
            pass

    # NVIDIA GPU
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            timeout=2, stderr=subprocess.DEVNULL
        )
        for line in out.decode().strip().split('\n'):
            temps.append(float(line))
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    return max(temps) if temps else None


def temp_to_color(temp):
    """Convert temperature to RGB color.
    < 65: None (Game Mode prevails)
    65-80: yellow→red gradient
    > 80: red (blinking)
    """
    if temp < TEMP_THRESHOLD_WARM:
        return None, False  # below threshold, no overlay
    elif temp >= TEMP_THRESHOLD_HOT:
        return (255, 0, 0), True  # red, blink
    else:
        # Gradient: yellow(65) → red(80)
        t = (temp - TEMP_THRESHOLD_WARM) / (TEMP_THRESHOLD_HOT - TEMP_THRESHOLD_WARM)
        r = 255
        g = int(255 * (1 - t))
        return (r, g, 0), False


def update_temperature():
    """Update temperature overlay state."""
    global temp_color, temp_blink, temp_last_read, temp_current
    now = time.time()
    if now - temp_last_read < TEMP_READ_INTERVAL:
        return
    temp_last_read = now

    temp = get_max_temperature()
    if temp is None:
        temp_color = None
        temp_current = 0.0
        return

    temp_current = temp
    temp_color, temp_blink = temp_to_color(temp)


# ══════════════════════════════════════════════════════════════════
# Notification overlay (DBus)
# ══════════════════════════════════════════════════════════════════

def start_notification_listener():
    """Listen for Steam notifications via DBus in a background thread."""
    global notif_active, notif_end_time, notif_color

    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError:
        print("dbus-python not available, notification overlay disabled", file=sys.stderr)
        return

    def on_notification(bus_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout):
        global notif_active, notif_end_time, notif_color
        with overlay_lock:
            # Gold for achievements, blue for messages
            summary_lower = summary.lower() if summary else ""
            if "achievement" in summary_lower or "conquista" in summary_lower:
                notif_color = (255, 215, 0)  # gold
            else:
                notif_color = (0, 120, 255)  # blue
            notif_active = True
            notif_end_time = time.time() + NOTIF_DURATION

    def dbus_thread():
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus.add_signal_receiver(
            on_notification,
            dbus_interface="org.freedesktop.Notifications",
            signal_name="Notify",
            bus_name="org.freedesktop.Notifications",
            path="/org/freedesktop/Notifications"
        )
        loop = GLib.MainLoop()
        while running:
            ctx = loop.get_context()
            ctx.iteration(True)

    t = threading.Thread(target=dbus_thread, daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════
# Audio reactive overlay
# ══════════════════════════════════════════════════════════════════

def start_audio_monitor():
    """Capture system audio level via PipeWire/PulseAudio monitor in a background thread."""
    global audio_process

    def find_default_sink_id():
        """Find the default sink node ID for PipeWire capture."""
        try:
            # wpctl gives us the default sink ID directly
            out = subprocess.check_output(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                timeout=2, stderr=subprocess.DEVNULL
            ).decode()
            for line in out.split('\n'):
                if 'id' in line and 'object.id' not in line:
                    # First line like "id 51, type ..."
                    parts = line.strip().split()
                    for i, p in enumerate(parts):
                        if p == 'id':
                            return parts[i + 1].rstrip(',')
            # Fallback: parse from wpctl status
            out2 = subprocess.check_output(
                ["wpctl", "status"], timeout=2, stderr=subprocess.DEVNULL
            ).decode()
            for line in out2.split('\n'):
                if '*' in line and 'vol:' in line:
                    # e.g. " *   51. HD-Audio Generic ..."
                    parts = line.strip().lstrip('*').strip().split('.')
                    return parts[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            pass
        return None

    def audio_thread():
        global audio_level, audio_peak, audio_process
        sink_id = find_default_sink_id()
        if not sink_id:
            print("No default audio sink found, audio overlay disabled", file=sys.stderr)
            return

        RATE = 48000  # native rate for minimal latency
        # Read ~50 updates/sec: 48000/50 = 960 samples per chunk
        SAMPLES_PER_UPDATE = RATE // 50
        CHUNK_BYTES = SAMPLES_PER_UPDATE * 2  # s16 = 2 bytes/sample

        try:
            # pw-record with stream.capture.sink=true captures audio from a sink
            audio_process = subprocess.Popen(
                ["pw-record", "--target", sink_id,
                 "-P", "{ stream.capture.sink = true }",
                 "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            print(f"Audio: using pw-record on sink {sink_id} at {RATE}Hz "
                  f"({SAMPLES_PER_UPDATE} samples/update)", file=sys.stderr)
        except OSError as e:
            print(f"pw-record not available ({e}), audio overlay disabled", file=sys.stderr)
            return

        # Skip WAV header (44 bytes)
        header = audio_process.stdout.read(44)
        if len(header) < 44:
            print("Audio: failed to read WAV header from pw-record", file=sys.stderr)
            return

        import struct
        while running and audio_process.poll() is None:
            data = audio_process.stdout.read(CHUNK_BYTES)
            if len(data) < 2:
                break
            # Calculate RMS of the chunk for accurate level
            n_samples = len(data) // 2
            samples = struct.unpack(f'<{n_samples}h', data[:n_samples * 2])
            rms = (sum(s * s for s in samples) / n_samples) ** 0.5
            level = min(rms / 32768.0 * 6.0, 1.0)  # amplify for VU visibility
            with overlay_lock:
                audio_level = audio_level * 0.3 + level * 0.7  # fast attack
                # Peak hold with decay
                if level > audio_peak:
                    audio_peak = level
                else:
                    audio_peak = max(0.0, audio_peak - 0.03)

        if audio_process:
            audio_process.terminate()

    t = threading.Thread(target=audio_thread, daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════
# Overlay application
# ══════════════════════════════════════════════════════════════════

# Snapshot header offsets
OFFSET_ENABLED = 24
OFFSET_EFFECT = 25
OFFSET_BRIGHTNESS_SCALE = 26
EFFECT_MANUAL = 1


def force_manual_mode(data):
    """Force snapshot to manual mode so ESP renders raw pixels without local effects."""
    data[OFFSET_ENABLED] = 1
    data[OFFSET_EFFECT] = EFFECT_MANUAL
    data[OFFSET_BRIGHTNESS_SCALE] = 255


def render_vu_meter(data, out_leds, level, peak):
    """Render a VU meter: LEDs fill from left to right based on audio level.
    Color: green (low) → yellow (mid) → red (high).
    """
    force_manual_mode(data)
    lit_count = level * out_leds  # fractional number of lit LEDs
    peak_led = int(peak * (out_leds - 1))  # peak indicator position

    for i in range(out_leds):
        off = PIXELS_OFFSET + i * PIXEL_SIZE
        # VU color gradient per LED position
        t = i / max(out_leds - 1, 1)  # 0.0 to 1.0
        if t < 0.5:
            r, g, b = int(255 * t * 2), 255, 0  # green → yellow
        else:
            r, g, b = 255, int(255 * (1 - (t - 0.5) * 2)), 0  # yellow → red

        if i < int(lit_count):
            br = 255
        elif i < lit_count + 1 and lit_count > 0:
            # Partial LED (fractional brightness)
            br = int(255 * (lit_count - int(lit_count)))
        elif i == peak_led and peak > 0.05:
            # Peak hold indicator
            br = 180
        else:
            br = 0

        data[off + 0] = r
        data[off + 1] = g
        data[off + 2] = b
        data[off + 3] = br


def apply_overlays(snapshot, out_leds):
    """Apply overlay layers on top of the remapped snapshot.

    Priority:
      1. Notification (always highest)
      2. Audio VU meter (main overlay when audio is playing)
      3. Temperature (only when >=65°C; alternates with audio every 10s)
      Below 65°C with no audio: Game Mode prevails.
    """
    global notif_active, temp_blink_state

    data = bytearray(snapshot)
    now = time.time()

    with overlay_lock:
        # Priority 1 (highest): Notification flash
        if notif_overlay_enabled and notif_active:
            if now > notif_end_time:
                notif_active = False
            else:
                force_manual_mode(data)
                flash_on = int((now - (notif_end_time - NOTIF_DURATION)) / 0.2) % 2 == 0
                br = 255 if flash_on else 80
                r, g, b = notif_color
                for i in range(out_leds):
                    off = PIXELS_OFFSET + i * PIXEL_SIZE
                    data[off + 0] = r
                    data[off + 1] = g
                    data[off + 2] = b
                    data[off + 3] = br
                return bytes(data)

        has_audio = audio_overlay_enabled and audio_level > 0.02
        has_temp = temp_overlay_enabled and temp_color is not None  # None means <65°C

        if has_audio and has_temp:
            # Both active: alternate every 10s
            cycle = int(now / TEMP_SHOW_CYCLE) % 2
            if cycle == 0:
                # Show audio VU meter
                render_vu_meter(data, out_leds, audio_level, audio_peak)
            else:
                # Show temperature
                force_manual_mode(data)
                r, g, b = temp_color
                if temp_blink:
                    temp_blink_state = int(now * 4) % 2 == 0
                    br = 255 if temp_blink_state else 0
                else:
                    br = 255
                for i in range(out_leds):
                    off = PIXELS_OFFSET + i * PIXEL_SIZE
                    data[off + 0] = r
                    data[off + 1] = g
                    data[off + 2] = b
                    data[off + 3] = br
            return bytes(data)

        elif has_audio:
            # Audio only (temp < 65°C): show VU meter
            render_vu_meter(data, out_leds, audio_level, audio_peak)
            return bytes(data)

        elif has_temp:
            # Temperature only (no audio): show temp bar
            force_manual_mode(data)
            r, g, b = temp_color
            if temp_blink:
                temp_blink_state = int(now * 4) % 2 == 0
                br = 255 if temp_blink_state else 0
            else:
                br = 255
            for i in range(out_leds):
                off = PIXELS_OFFSET + i * PIXEL_SIZE
                data[off + 0] = r
                data[off + 1] = g
                data[off + 2] = b
                data[off + 3] = br
            return bytes(data)

    # No overlay active: Game Mode prevails
    return bytes(data)


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def shutdown(signum, frame):
    global running
    running = False


def main():
    global latest, running
    global temp_overlay_enabled, notif_overlay_enabled, audio_overlay_enabled

    parser = argparse.ArgumentParser(
        description="SteamOS LED bar server with overlay effects."
    )
    parser.add_argument("--device", default=DEFAULT_DEVICE,
                        help="path to the valve-leds-shim device node")
    parser.add_argument("--host", default="0.0.0.0",
                        help="TCP bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="TCP bind port")
    parser.add_argument("--leds", type=int, default=DEFAULT_LEDS,
                        help="number of output LEDs (remaps 17 source LEDs)")
    parser.add_argument("--temp", action="store_true",
                        help="enable temperature overlay")
    parser.add_argument("--notify", action="store_true",
                        help="enable notification overlay (achievements/messages)")
    parser.add_argument("--audio", action="store_true",
                        help="enable audio reactive overlay")
    args = parser.parse_args()

    global num_output_leds
    num_output_leds = max(1, min(args.leds, SRC_NUM_LEDS))

    temp_overlay_enabled = args.temp
    notif_overlay_enabled = args.notify
    audio_overlay_enabled = args.audio

    led_fd = os.open(args.device, os.O_RDONLY)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(5)
    server.setblocking(False)

    sel = selectors.DefaultSelector()
    sel.register(server, selectors.EVENT_READ, "server")

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start overlay threads
    overlays_active = []
    if temp_overlay_enabled:
        overlays_active.append("temp")
    if notif_overlay_enabled:
        start_notification_listener()
        overlays_active.append("notify")
    if audio_overlay_enabled:
        start_audio_monitor()
        overlays_active.append("audio")

    overlays_str = ", ".join(overlays_active) if overlays_active else "none"
    print(f"listening on {args.host}:{args.port}, reading from {args.device}, "
          f"output LEDs: {num_output_leds}, overlays: {overlays_str}",
          file=sys.stderr)

    initial = read_snapshot(led_fd)
    if initial:
        latest = initial

    while running:
        snap = read_snapshot(led_fd)
        if snap:
            remapped = remap_snapshot(snap, num_output_leds)

            # Update temperature if enabled
            if temp_overlay_enabled:
                update_temperature()

            # Apply overlays
            final = apply_overlays(remapped, num_output_leds)

            if final != latest:
                latest = final
                broadcast(latest)
        else:
            # Even without new snapshot, overlays may change (blink, audio)
            if latest and (temp_overlay_enabled or notif_overlay_enabled or audio_overlay_enabled):
                final = apply_overlays(latest, num_output_leds)
                if final != latest:
                    latest = final
                    broadcast(latest)

        try:
            events = sel.select(timeout=POLL_INTERVAL)
        except InterruptedError:
            continue

        for key, _ in events:
            if key.data == "server":
                accept_client(key.fileobj)

    print("shutting down", file=sys.stderr)
    if audio_process:
        audio_process.terminate()
    for c in list(clients):
        remove_client(c)
    server.close()
    os.close(led_fd)


if __name__ == "__main__":
    main()
