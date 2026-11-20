#!/usr/bin/python3
"""Switch the two uHandPi controllers using their existing systemd units."""
import argparse
import fcntl
import os
import subprocess
import sys
import time

UNITS = {"server": "uhand-server.service", "vendor": "uhandpi.service"}


def ctl(*args):
    return subprocess.run(
        ["/usr/bin/systemctl", "--no-pager", *args], check=True,
        stdout=subprocess.PIPE, text=True,
    ).stdout


def state(unit):
    fields = dict(line.split("=", 1) for line in ctl(
        "show", unit, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
        "-p", "UnitFileState", "-p", "MainPID", "-p", "NRestarts",
    ).splitlines())
    if fields["LoadState"] != "loaded":
        raise RuntimeError(f"{unit}: {fields['LoadState']}")
    return fields


def display():
    for name, unit in UNITS.items():
        info = state(unit)
        print(f"{name:6} {unit:22} {info['ActiveState']}/{info['SubState']}  boot={info['UnitFileState']}")


def stop(unit):
    ctl("stop", unit)
    if state(unit)["ActiveState"] not in ("inactive", "failed"):
        raise RuntimeError(f"{unit} did not stop")


def start(unit):
    ctl("start", unit)
    initial = state(unit)
    for _ in range(6):
        time.sleep(0.5)
        info = state(unit)
        if (info["ActiveState"] != "active" or info["SubState"] != "running"
                or info["MainPID"] == "0" or info["MainPID"] != initial["MainPID"]
                or info["NRestarts"] != initial["NRestarts"]):
            raise RuntimeError(f"{unit} did not stay running")


def set_boot(unit, desired):
    if state(unit)["UnitFileState"] != desired:
        ctl("enable" if desired == "enabled" else "disable", unit)
        if state(unit)["UnitFileState"] != desired:
            raise RuntimeError(f"{unit}: could not set boot state to {desired}")


def switch(mode, persist):
    before = {name: state(unit) for name, unit in UNITS.items()}
    if any(s["ActiveState"] not in ("active", "inactive", "failed") for s in before.values()):
        raise RuntimeError("Service transition in progress. Try again after it finishes.")
    active = [name for name, s in before.items() if s["ActiveState"] == "active"]
    if len(active) > 1 or (mode == "toggle" and not active):
        raise RuntimeError("Toggle requires exactly one running service." if mode == "toggle"
                           else "Both services are active. Inspect them before switching.")
    if persist and any(s["UnitFileState"] not in ("enabled", "disabled") for s in before.values()):
        raise RuntimeError("Unexpected boot configuration. Inspect both units first.")
    if mode == "toggle":
        mode = "vendor" if active == ["server"] else "server"
    other = "server" if mode == "vendor" else "vendor"
    target = UNITS[mode]
    previous = UNITS[other]
    change = mode not in active
    try:
        if change:
            if other in active:
                stop(previous)
            start(target)
        if persist:
            set_boot(previous, "disabled")
            set_boot(target, "enabled")
    except (RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as cause:
        print("Switch failed. Restoring the previous mode.", file=sys.stderr)
        if change:
            stop(target)
            if other in active:
                start(previous)
        if persist:
            for name, unit in UNITS.items():
                set_boot(unit, before[name]["UnitFileState"])
        raise RuntimeError(f"Previous mode restored. Cause: {cause}") from cause


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="status",
                        choices=("status", "toggle", "server", "vendor"))
    parser.add_argument("--boot", action="store_true", help="also use the chosen service after reboot")
    args = parser.parse_args()
    if args.mode == "status":
        if args.boot:
            parser.error("--boot requires toggle, server, or vendor")
    else:
        if os.geteuid() != 0:
            parser.error("use sudo to change the active service")
        with open("/run/uhand-mode.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.exit(1, "Another mode switch is running.\n")
            switch(args.mode, args.boot)
    display()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
