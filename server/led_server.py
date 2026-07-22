#!/usr/bin/env python3
"""Forward 100-byte VLED snapshots from /dev/valve-leds-shim to TCP clients."""

import argparse
import os
import selectors
import signal
import socket
import struct
import sys

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
        # Map output LED i to a fractional range over the 17 source LEDs
        start = i * SRC_NUM_LEDS / out_leds
        end = (i + 1) * SRC_NUM_LEDS / out_leds

        r_sum, g_sum, b_sum, br_sum = 0.0, 0.0, 0.0, 0.0
        weight_total = 0.0

        j = int(start)
        while j < end and j < SRC_NUM_LEDS:
            # Weight: how much of source LED j falls within [start, end)
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

    # Pad remaining pixel slots with zeros to keep snapshot at 100 bytes
    padding = bytearray((SRC_NUM_LEDS - out_leds) * PIXEL_SIZE)
    return bytes(header + pixels_out + padding)


def shutdown(signum, frame):
    global running
    running = False


def main():
    global latest, running

    parser = argparse.ArgumentParser(
        description="Expose /dev/valve-leds-shim over TCP for an ESP32 LED bar."
    )
    parser.add_argument("--device", default=DEFAULT_DEVICE,
                        help="path to the valve-leds-shim device node")
    parser.add_argument("--host", default="0.0.0.0",
                        help="TCP bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="TCP bind port")
    parser.add_argument("--leds", type=int, default=DEFAULT_LEDS,
                        help="number of output LEDs (remaps 17 source LEDs)")
    args = parser.parse_args()

    global num_output_leds
    num_output_leds = max(1, min(args.leds, SRC_NUM_LEDS))

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

    print(f"listening on {args.host}:{args.port}, reading from {args.device}, "
          f"output LEDs: {num_output_leds}",
          file=sys.stderr)

    # Send an initial snapshot so the first client gets data immediately.
    initial = read_snapshot(led_fd)
    if initial:
        latest = initial

    while running:
        # Poll the LED device every cycle regardless of select events.
        snap = read_snapshot(led_fd)
        if snap:
            remapped = remap_snapshot(snap, num_output_leds)
            if remapped != latest:
                latest = remapped
                broadcast(latest)

        try:
            events = sel.select(timeout=POLL_INTERVAL)
        except InterruptedError:
            continue

        for key, _ in events:
            if key.data == "server":
                accept_client(key.fileobj)

    print("shutting down", file=sys.stderr)
    for c in list(clients):
        remove_client(c)
    server.close()
    os.close(led_fd)


if __name__ == "__main__":
    main()
