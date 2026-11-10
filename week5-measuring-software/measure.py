"""Measure the energy of one command, on Linux, macOS or Windows.

    python measure.py --label numpy -- python workload.py numpy-matmul

Each run appends one row to runs.csv (change with --csv). Meters (--meter):

  rapl        Linux, Intel or AMD: CPU package energy counters. Needs root:
              sudo "$(which python)" measure.py ... -- "$(which python)" workload.py ...
  macmon      macOS, Apple Silicon: CPU+GPU+Neural Engine power, no sudo.
              Install with `brew install macmon`.
  codecarbon  Any OS: uses RAPL, powermetrics or the Windows Energy Meter Interface
              when it can, otherwise an ESTIMATE from the CPU model. The `mode`
              column says which. pip install codecarbon
  battery     Any laptop, running on battery: whole-system power from the battery.
              Unplug the charger first.
  nvidia      NVIDIA GPU board energy from the driver (NVML). pip install nvidia-ml-py
              --gpus 0 measures only GPU 0 (as numbered by nvidia-smi); default all.
  rapl+nvidia Linux with an NVIDIA GPU: CPU package + GPU, over the same run. Use this
              for Part B: RAPL alone does not see the GPU. Needs root, like rapl.
  auto        (default) rapl on Linux, macmon on macOS, otherwise codecarbon.

Run the same workload with two different meters and compare: they measure different
things (see the `scope` column).
"""

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from statistics import mean

FIELDS = ["timestamp", "label", "meter", "scope", "mode", "seconds", "energy_j", "avg_w",
          "samples", "task", "device", "n", "reps", "work_seconds", "checksum", "exit_code",
          "valid", "os", "cpu", "extra"]


class Sampler:
    """Calls read_watts() every `interval` seconds in a background thread."""

    def __init__(self, read_watts, interval):
        self.read_watts, self.interval = read_watts, interval
        self.samples, self._stop = [], threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                watts = self.read_watts()
            except Exception as exc:  # keep sampling; one bad read shouldn't end the run
                print(f"[measure] sample failed: {exc}", file=sys.stderr)
                watts = None
            if watts is not None:
                self.samples.append(watts)
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


# ---------------------------------------------------------------- RAPL (Linux)

RAPL_ROOT = Path(os.environ.get("RAPL_ROOT", "/sys/class/powercap"))


def rapl_zones():
    # /sys/class/powercap lists every zone (intel-rapl:0, intel-rapl:0:0, ...) at the top
    # level. intel-rapl-mmio:* duplicates the package zone, so the pattern skips it.
    zones = {}
    for energy in sorted(RAPL_ROOT.glob("intel-rapl:*/energy_uj")):
        zone = energy.parent
        name = (zone / "name").read_text().strip()
        wrap = int((zone / "max_energy_range_uj").read_text())
        int(energy.read_text())  # raises PermissionError if not root
        zones[zone.name] = (name, energy, wrap)
    if not zones:
        raise SystemExit(f"No RAPL zones under {RAPL_ROOT}. Not Linux, or a VM/container/WSL.")
    return zones


def run_rapl(run):
    """`run` runs the command and returns (seconds, proc), or (seconds, proc, result) when
    another meter wraps it (rapl+nvidia)."""
    try:
        zones = rapl_zones()
    except PermissionError:
        raise SystemExit("RAPL needs root: sudo \"$(which python)\" measure.py ... "
                         "-- \"$(which python)\" workload.py ...")
    before = {k: int(z[1].read_text()) for k, z in zones.items()}
    seconds, proc, *_ = run()
    after = {k: int(z[1].read_text()) for k, z in zones.items()}
    joules = {f"{k} ({zones[k][0]})": ((after[k] - before[k]) % zones[k][2]) / 1e6 for k in zones}
    # Top-level "package-N" zones together are the CPU total; psys (whole platform) is kept separate.
    package = sum(j for k, j in joules.items() if re.fullmatch(r"intel-rapl:\d+ \(package-\d+\)", k))
    return seconds, proc, {"scope": "CPU package", "mode": "measured", "energy_j": package,
                           "samples": "", "extra": joules}


# ------------------------------------------------------------ NVIDIA GPUs (Linux, Windows)

def run_nvidia(run, interval, gpus=None):
    """GPU board energy from NVML (pip install nvidia-ml-py). Uses the energy counter
    (Volta and newer); older GPUs fall back to sampling power. `gpus` is a list of NVML
    indices as `nvidia-smi` numbers them; default all."""
    try:
        import pynvml
    except ImportError:
        raise SystemExit("pip install nvidia-ml-py")
    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError as exc:
        raise SystemExit(f"NVML not available ({exc}): no NVIDIA GPU or driver.")
    try:
        count = pynvml.nvmlDeviceGetCount()
        indices = gpus if gpus is not None else list(range(count))
        if not indices or any(not 0 <= i < count for i in indices):
            raise SystemExit(f"--gpus must be between 0 and {count - 1} (see nvidia-smi)")
        handles = {i: pynvml.nvmlDeviceGetHandleByIndex(i) for i in indices}
        names = {i: pynvml.nvmlDeviceGetName(h) for i, h in handles.items()}
        names = {i: n.decode() if isinstance(n, bytes) else n for i, n in names.items()}

        def energy_mj():
            return {i: pynvml.nvmlDeviceGetTotalEnergyConsumption(h) for i, h in handles.items()}
        try:
            before = energy_mj()
            counter = True
        except pynvml.NVMLError:
            counter = False

        def read_watts():
            return {i: pynvml.nvmlDeviceGetPowerUsage(h) / 1000 for i, h in handles.items()}
        with Sampler(read_watts, interval) as s:  # power samples, also kept when the counter works
            seconds, proc = run()
        if counter:
            after = energy_mj()
            joules = {i: (after[i] - before[i]) / 1000 for i in indices}
            mode = "measured (NVML energy counter)"
        else:
            joules = {i: mean(x[i] for x in s.samples) * seconds if s.samples else 0.0 for i in indices}
            mode = "measured (NVML power samples)"
    finally:
        pynvml.nvmlShutdown()
    extra = {f"gpu{i} ({names[i]})": round(j, 2) for i, j in joules.items()}
    if s.samples:
        extra["max_gpu_w"] = round(max(sum(x.values()) for x in s.samples), 1)
    return seconds, proc, {"scope": "GPU board" + ("s" if len(indices) > 1 else ""), "mode": mode,
                           "energy_j": sum(joules.values()), "samples": len(s.samples), "extra": extra}


def run_rapl_nvidia(cmd, interval, gpus):
    """CPU package (RAPL) + GPU board (NVML), measured over the same run."""
    inner = {}

    def gpu_run():
        seconds, proc, inner["r"] = run_nvidia(lambda: run_command(cmd), interval, gpus)
        return seconds, proc
    seconds, proc, cpu = run_rapl(gpu_run)
    gpu = inner["r"]
    extra = {"cpu_package_j": round(cpu["energy_j"], 2), "gpu_j": round(gpu["energy_j"], 2),
             **cpu["extra"], **gpu["extra"]}
    return seconds, proc, {"scope": f"CPU package + {gpu['scope']}", "mode": f"measured (RAPL + {gpu['mode'][10:-1]})",
                           "energy_j": cpu["energy_j"] + gpu["energy_j"], "samples": gpu["samples"],
                           "extra": extra}


# ------------------------------------------------------------ macmon (macOS)

def run_macmon(cmd, interval):
    exe = shutil.which("macmon")
    if not exe:
        raise SystemExit("macmon not found. Install it with: brew install macmon")
    mon = subprocess.Popen([exe, "pipe", "-i", str(int(interval * 1000))],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    samples, started = [], threading.Event()

    def reader():
        for line in mon.stdout:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if started.is_set():
                samples.append(data)
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(interval * 2)  # let macmon settle before the command starts
    started.set()
    seconds, proc = run_command(cmd)
    time.sleep(interval)  # catch the sample covering the end of the run
    started.clear()
    mon.terminate()
    mon.wait()
    if len(samples) < 3:
        print(f"[measure] only {len(samples)} macmon samples; use longer runs", file=sys.stderr)
    soc = [s.get("all_power") for s in samples if s.get("all_power") is not None]
    system = [s.get("sys_power") for s in samples if s.get("sys_power") is not None]
    parts = {k: mean(s.get(k) or 0 for s in samples) if samples else 0
             for k in ("cpu_power", "gpu_power", "ane_power", "ram_power")}
    extra = {f"avg_{k}": round(v, 3) for k, v in parts.items()}
    if system:
        extra["sys_energy_j"] = round(mean(system) * seconds, 2)
    return seconds, proc, {"scope": "SoC (CPU+GPU+ANE)", "mode": "measured (OS power model)",
                           "energy_j": mean(soc) * seconds if soc else 0.0,
                           "samples": len(samples), "extra": extra}


# ------------------------------------------------------------ CodeCarbon (any OS)

def run_codecarbon(cmd, interval):
    try:
        import codecarbon
        from codecarbon import OfflineEmissionsTracker
    except ImportError:
        raise SystemExit("pip install codecarbon")
    # CODECARBON_LOG_LEVEL=warning (or debug) shows why a run was not measured.
    tracker = OfflineEmissionsTracker(country_iso_code="SVN", measure_power_secs=interval,
                                      tracking_mode="machine", save_to_file=False,
                                      allow_multiple_runs=True,
                                      log_level=os.environ.get("CODECARBON_LOG_LEVEL", "error"))
    tracker.start()
    seconds, proc = run_command(cmd)
    tracker.stop()
    d = getattr(tracker, "final_emissions_data", None)
    if d is None:
        # stop() only stores results when start() really started measuring.
        raise SystemExit(
            f"CodeCarbon {codecarbon.__version__} did not measure this run. Run again with "
            "CODECARBON_LOG_LEVEL=warning set to see why. A common cause is a leftover lock file: "
            f"delete {os.path.join(tempfile.gettempdir(), '.codecarbon.lock')} and retry.")
    cpu_modes = [type(h).__name__ + ":" + str(getattr(h, "_mode", "?"))
                 for h in getattr(tracker, "_hardware", []) if type(h).__name__ == "CPU"]
    kwh = {"cpu": d.cpu_energy, "gpu": d.gpu_energy, "ram": d.ram_energy}
    extra = {f"{k}_j": round(v * 3.6e6, 2) for k, v in kwh.items()}
    extra.update(cpu_model=d.cpu_model, total_j=round(d.energy_consumed * 3.6e6, 2))
    mode = ",".join(cpu_modes) or "unknown"
    return seconds, proc, {"scope": "CPU (CodeCarbon)", "mode": mode,
                           "energy_j": d.cpu_energy * 3.6e6, "samples": "", "extra": extra}


# ------------------------------------------------------------ Battery (any laptop)

def battery_reader():
    """Return (read_watts, on_battery) for this OS. Watts are positive while discharging."""
    system = platform.system()
    if system == "Linux":
        bats = sorted(Path("/sys/class/power_supply").glob("BAT*"))
        if not bats:
            raise SystemExit("No battery found under /sys/class/power_supply")
        bat = bats[0]

        def read():
            if (bat / "power_now").exists():
                return int((bat / "power_now").read_text()) / 1e6
            return int((bat / "current_now").read_text()) * int((bat / "voltage_now").read_text()) / 1e12
        return read, lambda: (bat / "status").read_text().strip() == "Discharging"
    if system == "Darwin":
        def props():
            out = subprocess.run(["ioreg", "-rn", "AppleSmartBattery"], capture_output=True, text=True).stdout
            return {k: v for k, v in re.findall(r'"(\w+)" = (\S+)', out)}

        def signed(v):
            v = int(v)
            return v - 2 ** 64 if v >= 2 ** 63 else v  # ioreg prints negative values as unsigned

        def read():
            p = props()
            return -signed(p["InstantAmperage"]) * int(p["Voltage"]) / 1e6  # mA x mV -> W
        return read, lambda: props().get("ExternalConnected") == "No"
    if system == "Windows":
        ps = ["powershell", "-NoProfile", "-Command",
              "$b = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus; "
              "\"$($b.DischargeRate) $($b.PowerOnline)\""]

        def query():
            return subprocess.run(ps, capture_output=True, text=True).stdout.split()
        return (lambda: int(query()[0]) / 1000), (lambda: query()[1] == "False")
    raise SystemExit(f"battery meter not supported on {system}")


def run_battery(cmd, interval, force):
    read, on_battery = battery_reader()
    if not on_battery() and not force:
        raise SystemExit("The charger is connected: the battery reading would be wrong. "
                         "Unplug it and try again (or pass --force).")
    with Sampler(read, interval) as s:
        seconds, proc = run_command(cmd)
    if len(s.samples) < 5:
        print(f"[measure] only {len(s.samples)} battery samples; use runs of 30 s or more",
              file=sys.stderr)
    watts = mean(s.samples) if s.samples else 0.0
    return seconds, proc, {"scope": "whole laptop (battery)", "mode": "measured (fuel gauge)",
                           "energy_j": watts * seconds, "samples": len(s.samples),
                           "extra": {"min_w": round(min(s.samples), 2) if s.samples else None,
                                     "max_w": round(max(s.samples), 2) if s.samples else None}}


# ------------------------------------------------------------ common

SLEPT = {}


def run_command(cmd):
    """Run the command, show its output, and return (seconds, CompletedProcess)."""
    wall, start = time.time(), time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    seconds = time.perf_counter() - start
    # The monotonic clock stops while the machine sleeps (macOS, Linux); the wall clock doesn't.
    SLEPT["seconds"] = (time.time() - wall) - seconds
    sys.stdout.write(proc.stdout)
    return seconds, proc


def workload_info(stdout):
    for line in reversed(stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {}


def cpu_name():
    if platform.system() == "Darwin":
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                              capture_output=True, text=True).stdout.strip()
    if platform.system() == "Linux":
        m = re.search(r"model name\s*:\s*(.+)", Path("/proc/cpuinfo").read_text())
        return m.group(1) if m else platform.processor()
    return platform.processor()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                epilog=__doc__.split("\n", 2)[2],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--meter", default="auto",
                   choices=["auto", "rapl", "macmon", "codecarbon", "battery", "nvidia", "rapl+nvidia"])
    p.add_argument("--gpus", help="nvidia meters: GPU indices to measure, as nvidia-smi numbers them "
                                  "(e.g. 0 or 0,1); default all")
    p.add_argument("--label", required=True, help="name of this test, e.g. numpy or idle")
    p.add_argument("--csv", default="runs.csv")
    p.add_argument("--interval", type=float, default=0.5, help="seconds between samples")
    p.add_argument("--force", action="store_true", help="battery meter: measure even when plugged in")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command to measure")
    args = p.parse_args()
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if cmd and Path(cmd[0]).stem.lower() in ("python", "python3", "py"):
        # Run the workload with this same interpreter. A bare "python" can resolve to a
        # different one: on Windows a venv's python.exe launches the base install, and the
        # child search starts in that folder; under sudo, root's PATH has no venv.
        cmd = [sys.executable] + cmd[1:]
    if not cmd:
        p.error("give the command after --")

    if Path(args.csv).exists():
        with open(args.csv, newline="") as f:
            others = {f"{r['cpu']} ({r['os']})" for r in csv.DictReader(f)} - {f"{cpu_name()} ({platform.system()})"}
        if others:
            print(f"[measure] WARNING: {args.csv} already has runs from another machine "
                  f"({'; '.join(sorted(others))}). Start a new file, e.g. --csv runs-{platform.system().lower()}.csv",
                  file=sys.stderr)

    meter = args.meter
    if meter == "auto":
        meter = {"Linux": "rapl", "Darwin": "macmon"}.get(platform.system(), "codecarbon")
    gpus = [int(i) for i in args.gpus.split(",")] if args.gpus else None
    if "nvidia" in meter:
        # Make cuda:0 in the workload the same GPU as nvidia-smi's GPU 0 (CUDA's default
        # order is fastest first, which can differ on machines with mixed GPUs).
        os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    run = {"rapl": lambda: run_rapl(lambda: run_command(cmd)),
           "nvidia": lambda: run_nvidia(lambda: run_command(cmd), args.interval, gpus),
           "rapl+nvidia": lambda: run_rapl_nvidia(cmd, args.interval, gpus),
           "macmon": lambda: run_macmon(cmd, args.interval),
           "codecarbon": lambda: run_codecarbon(cmd, max(args.interval, 0.5)),
           "battery": lambda: run_battery(cmd, max(args.interval, 1.0), args.force)}[meter]
    seconds, proc, r = run()

    info = workload_info(proc.stdout)
    slept = SLEPT.get("seconds", 0)
    valid = "yes" if slept < 2 else f"no: machine slept for {slept:.0f} s during the run"
    row = {"timestamp": datetime.now().isoformat(timespec="seconds"), "label": args.label,
           "meter": meter, "scope": r["scope"], "mode": r["mode"], "seconds": round(seconds, 3),
           "energy_j": round(r["energy_j"], 2), "avg_w": round(r["energy_j"] / seconds, 2),
           "samples": r["samples"], "task": info.get("task", ""), "device": info.get("device", ""),
           "n": info.get("n", ""), "reps": info.get("reps", ""),
           "work_seconds": info.get("work_seconds", ""), "checksum": info.get("checksum", ""),
           "exit_code": proc.returncode, "valid": valid,
           "os": platform.system(), "cpu": cpu_name(), "extra": json.dumps(r["extra"])}
    new = not Path(args.csv).exists()
    with open(args.csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)

    print(f"[measure] {args.label}: {row['energy_j']} J in {row['seconds']} s = {row['avg_w']} W "
          f"({meter}, {r['scope']}, {r['mode']}) -> {args.csv}", file=sys.stderr)
    if not valid.startswith("yes"):
        print(f"[measure] WARNING: {valid}; repeat this run", file=sys.stderr)
    if proc.returncode != 0:
        print(f"[measure] WARNING: command exited with code {proc.returncode}; this run is not valid",
              file=sys.stderr)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
