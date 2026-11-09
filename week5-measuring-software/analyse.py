"""Summarise runs.csv from measure.py as markdown tables.

    python analyse.py runs.csv
    python analyse.py runs.csv --idle idle --baseline python

For each meter: every run, then mean and SD per test, and energy per unit of work.
Energy per unit of work is what to compare: the tests do very different amounts of
work in the same time. "Above idle" removes what the machine draws doing nothing,
using the mean power of the --idle test measured with the same meter.
"""

import argparse
import csv
from collections import defaultdict
from statistics import mean, stdev

DEFAULT_N = {"torch-matmul": 2048}  # workload.py defaults; others use 120


def sd(xs):
    return stdev(xs) if len(xs) > 1 else 0.0


def si(joules):
    """Format small energies readably: J, mJ or µJ."""
    for scale, unit in ((1, "J"), (1e-3, "mJ"), (1e-6, "µJ"), (1e-9, "nJ")):
        if abs(joules) >= scale or unit == "nJ":
            return f"{joules / scale:.3g} {unit}"


def gflop(row):
    n = int(row.get("n") or DEFAULT_N.get(row["task"], 120))
    return 2 * n ** 3 * int(row["reps"] or 0) / 1e9


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("csv")
    p.add_argument("--idle", default="idle", help="label of the idle baseline test")
    p.add_argument("--baseline", help="label to compare the others against (e.g. python)")
    args = p.parse_args()

    with open(args.csv, newline="") as f:
        rows = [r for r in csv.DictReader(f)]
    ok = lambda r: r["exit_code"] == "0" and r.get("valid", "yes").startswith("yes")
    bad = [r for r in rows if not ok(r)]
    rows = [r for r in rows if ok(r)]
    if bad:
        print(f"*Skipped {len(bad)} invalid run(s): command failed or the machine slept.*\n")

    # Runs from different machines (e.g. a runs.csv copied to another computer) are kept apart.
    machine = lambda r: f"{r['cpu']} ({r['os']})"
    machines = sorted({machine(r) for r in rows})
    if len(machines) > 1:
        print(f"*This file has runs from {len(machines)} machines: {'; '.join(machines)}. "
              "They are analysed separately.*\n")
    by_meter = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = r["meter"] if len(machines) == 1 else f"{r['meter']} on {machine(r)}"
        by_meter[key][r["label"]].append(r)

    summary = {}
    for meter, labels in by_meter.items():
        first = next(iter(labels.values()))[0]
        print(f"## Meter: {meter}\n")
        print(f"Scope: {first['scope']}. Mode: {first['mode']}. Machine: {first['cpu']} ({first['os']}).\n")
        idle_w = mean(float(r["avg_w"]) for r in labels[args.idle]) if args.idle in labels else None

        for label, runs in labels.items():
            print(f"### {label}\n")
            print("| Run | Time (s) | Energy (J) | Energy (Wh) | Avg power (W) | Work done (reps) | Energy per rep |")
            print("|-----|----------|------------|-------------|---------------|------------------|----------------|")
            for i, r in enumerate(runs, 1):
                e, reps = float(r["energy_j"]), int(r["reps"] or 0)
                print(f"| {i} | {float(r['seconds']):.2f} | {e:.1f} | {e / 3600:.4f} | {float(r['avg_w']):.2f}"
                      f" | {reps:,} | {si(e / reps) if reps else '–'} |")
            col = lambda k: [float(r[k]) for r in runs]
            e, t, w = col("energy_j"), col("seconds"), col("avg_w")
            print(f"| **Mean** | **{mean(t):.2f}** | **{mean(e):.1f}** | **{mean(e) / 3600:.4f}**"
                  f" | **{mean(w):.2f}** | | |")
            print(f"| **SD** | {sd(t):.2f} | {sd(e):.1f} | {sd(e) / 3600:.4f} | {sd(w):.2f} | | |\n")

            if label == args.idle or not all(gflop(r) for r in runs):
                continue  # idle, or a command that reports no work
            per_gflop = [float(r["energy_j"]) / gflop(r) for r in runs]
            above = ([(float(r["energy_j"]) - idle_w * float(r["seconds"])) / gflop(r) for r in runs]
                     if idle_w is not None else None)
            summary[(meter, label)] = {
                "w": mean(w), "w_sd": sd(w),
                "gflops": mean(gflop(r) / float(r["work_seconds"]) for r in runs),
                "j_gflop": mean(per_gflop), "j_gflop_sd": sd(per_gflop),
                "above": mean(above) if above else None, "idle_w": idle_w}

        print(f"### Summary ({meter})\n")
        if idle_w is not None:
            print(f"Idle power: {idle_w:.2f} W.\n")
        print("| Test | Avg power (W) | Speed (GFLOP/s) | Energy per GFLOP | SD | Above idle, per GFLOP |"
              + (" Energy vs. baseline |" if args.baseline else ""))
        print("|------|---------------|-----------------|------------------|----|-----------------------|"
              + ("---------------------|" if args.baseline else ""))
        base = summary.get((meter, args.baseline))
        for (m, label), s in summary.items():
            if m != meter:
                continue
            ratio = f" {base['j_gflop'] / s['j_gflop']:,.1f}× less |" if base and label != args.baseline else (
                " – |" if args.baseline else "")
            print(f"| {label} | {s['w']:.2f} ± {s['w_sd']:.2f} | {s['gflops']:,.2f} | {si(s['j_gflop'])}"
                  f" | {si(s['j_gflop_sd'])} | {si(s['above']) if s['above'] is not None else '–'} |{ratio}")
        print()

    meters = sorted(by_meter)
    if len(meters) > 1:
        print("## Same tests, different meters (mean power, W)\n")
        print("| Test | " + " | ".join(meters) + " |")
        print("|------|" + "---|" * len(meters))
        labels = sorted({label for m in meters for label in by_meter[m]})
        for label in labels:
            cells = [f"{mean(float(r['avg_w']) for r in by_meter[m][label]):.2f}" if label in by_meter[m] else "–"
                     for m in meters]
            print(f"| {label} | " + " | ".join(cells) + " |")
        print()


if __name__ == "__main__":
    main()
