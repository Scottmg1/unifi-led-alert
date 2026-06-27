#!/usr/bin/env python3

import subprocess
import sys
import time
import threading

# ----------------------------- config -----------------------------
APS         = ["192.168.1.10", "192.168.1.11"]  # Place your UniFi AP management IPs here
SSH_USER    = "admin"                           # UniFi device SSH user (from UniFi Devices -> Device Updates & Settings -> Device SSH Settings -> Device SSH Authentication)
SSH_PASS_FILE = "/etc/unifi-led/pass"           # File with the AP password, chmod 600
WAN_TARGETS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
NUT_UPS     = "ups@localhost"                   # `upsc` target name
POLL        = 2.0                               # Seconds between evaluations
LEDBAR      = "/proc/ubnt_ledbar/color"

# Battery thresholds (runtime in seconds, charge in percent)
LOW_RUNTIME, CRIT_RUNTIME = 600, 180
LOW_CHARGE,  CRIT_CHARGE  = 50, 20
# ------------------------------------------------------------------

SSH = ["sshpass", "-f", SSH_PASS_FILE,
       "ssh",
       "-o", "ConnectTimeout=4",
       "-o", "StrictHostKeyChecking=no",
       "-o", "PubkeyAuthentication=no"]

ANIM_RED_FLASH = ["255,0,0", "0,0,0"]

ANIM_RED_BREATHE = [
    "9,0,0", "15,0,0", "25,0,0", "40,0,0", "61,0,0", "88,0,0", 
    "120,0,0", "159,0,0", "204,0,0", "255,0,0", "204,0,0", "159,0,0", 
    "120,0,0", "88,0,0", "61,0,0", "40,0,0", "25,0,0", "15,0,0"
]

ANIM_AMBER_PULSE = [
    "9,3,0", "15,6,0", "25,10,0", "40,16,0", "61,24,0", "88,35,0", 
    "120,48,0", "159,63,0", "204,81,0", "255,102,0", "204,81,0", "159,63,0", 
    "120,48,0", "88,35,0", "61,24,0", "40,16,0", "25,10,0", "15,6,0"
]

ANIM_PURPLE_BLINK = [
    "160,0,255", "0,0,0", "160,0,255", "0,0,0", "0,0,0", "0,0,0", "0,0,0"
]

MODES = {
    "POWER_CRIT":    ("anim",   ANIM_RED_BREATHE,  0.05),
    "POWER_LOW":     ("anim",   ANIM_AMBER_PULSE,  0.06),
    
    "POWER_BATTERY": ("static", "255,102,0",       1.0), 
    
    "AP_DOWN":       ("anim",   ANIM_PURPLE_BLINK, 0.15),
    "WAN_DOWN":      ("anim",   ANIM_RED_FLASH,    0.15),
    "NORMAL":        ("static", "0,0,0",           2.0),  # Off
}

ssh_pipes = {}
active_modes = {}


def get_ssh_pipe(ip):
    """Get or establish a persistent SSH stdin pipe to the AP."""
    if ip in ssh_pipes and ssh_pipes[ip].poll() is None:
        return ssh_pipes[ip]
    
    cmd = SSH + [f"{SSH_USER}@{ip}", f"while read -r line; do printf \"$line\" > {LEDBAR}; done"]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True, bufsize=1)
        ssh_pipes[ip] = proc
        return proc
    except Exception as e:
        print(f"[{ip}] Failed to open SSH stream: {e}", file=sys.stderr)
        return None


def write_led(ip, color_str):
    """Write an RGB color string to the AP's stream."""
    pipe = get_ssh_pipe(ip)
    if pipe and pipe.stdin:
        try:
            pipe.stdin.write(color_str + "\n")
            pipe.stdin.flush()
        except Exception:
            ssh_pipes.pop(ip, None)


def ap_worker_loop(ip):
    """Background thread per AP that cycles animation frames at native speeds."""
    frame_idx = 0
    last_mode_seen = None

    while True:
        mode = active_modes.get(ip)
        if not mode:
            time.sleep(0.5)
            continue

        kind, payload, delay = MODES[mode]

        if kind == "static":
            write_led(ip, payload)
            time.sleep(delay)
            continue

        if mode != last_mode_seen:
            frame_idx = 0
            last_mode_seen = mode

        current_frame = payload[frame_idx % len(payload)]
        write_led(ip, current_frame)
        frame_idx += 1
        time.sleep(delay)


def reachable(host):
    return subprocess.run(["ping", "-c1", "-W1", host],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def wan_down():
    return not any(reachable(t) for t in WAN_TARGETS)


def power_mode():
    """Return POWER_* mode if on battery, else None."""
    try:
        out = subprocess.run(["upsc", NUT_UPS], capture_output=True,
                             text=True, timeout=4).stdout
    except Exception:
        return None
    ups = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            ups[k.strip()] = v.strip()
    if "OB" not in ups.get("ups.status", "").split():
        return None
    runtime = int(ups["battery.runtime"]) if "battery.runtime" in ups else None
    charge  = int(float(ups["battery.charge"])) if "battery.charge" in ups else None
    if (runtime is not None and runtime <= CRIT_RUNTIME) or \
       (charge is not None and charge <= CRIT_CHARGE):
        return "POWER_CRIT"
    if (runtime is not None and runtime <= LOW_RUNTIME) or \
       (charge is not None and charge <= LOW_CHARGE):
        return "POWER_LOW"
    return "POWER_BATTERY"


def main():
    for ip in APS:
        t = threading.Thread(target=ap_worker_loop, args=(ip,), daemon=True)
        t.start()

    while True:
        pmode = power_mode()
        wdown = wan_down()
        reach = {ip: reachable(ip) for ip in APS}
        for ip in APS:
            if not reach[ip]:
                continue
            if pmode:
                mode = pmode
            elif any(not reach[o] for o in APS if o != ip):
                mode = "AP_DOWN"
            elif wdown:
                mode = "WAN_DOWN"
            else:
                mode = "NORMAL"
            
            if mode != active_modes.get(ip):
                print(f"{ip}: {active_modes.get(ip)} -> {mode}", flush=True)
                active_modes[ip] = mode
        time.sleep(POLL)


def demo(secs=10):
    """Walk both APs through every mode, `secs` each, looping until Ctrl-C."""
    order = ["POWER_BATTERY", "POWER_LOW", "POWER_CRIT",
             "AP_DOWN", "WAN_DOWN", "NORMAL"]
    
    for ip in APS:
        t = threading.Thread(target=ap_worker_loop, args=(ip,), daemon=True)
        t.start()

    print("DEMO mode -- Ctrl-C to stop", flush=True)
    try:
        while True:
            for mode in order:
                print(f"demo: {mode}", flush=True)
                for ip in APS:
                    active_modes[ip] = mode
                time.sleep(secs)
    except KeyboardInterrupt:
        for ip in APS:
            active_modes[ip] = "NORMAL"
        time.sleep(1)
        print("\ndemo stopped, LEDs off", flush=True)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        main()