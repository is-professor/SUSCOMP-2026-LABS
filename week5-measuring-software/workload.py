"""Workloads for the Week 5 energy lab. Runs on macOS, Linux and Windows.

Each run lasts about the same time (default 30 s) and counts how many matrix
multiplications it completes. Energy meters need long runs to be accurate; dividing
energy by the count gives joules per multiplication, which is fair to compare even
when one variant is 100x faster than another.

    python workload.py idle                         # baseline: does nothing for 30 s
    python workload.py python-matmul                # pure Python loops
    python workload.py numpy-matmul                 # same maths with NumPy
    python workload.py torch-matmul --device cpu
    python workload.py torch-matmul --device mps    # Apple Silicon GPU
    python workload.py torch-matmul --device cuda   # NVIDIA GPU
    python workload.py torch-matmul --device xpu    # Intel GPU (recent PyTorch)

Options: --seconds (run length), --reps (fixed work instead), --n (matrix size).
Prints one JSON line; the checksum lets you confirm variants compute the same result.
"""

import argparse
import json
import platform
import time


def repeat(step, seconds, reps):
    """Call step() for `reps` times, or until `seconds` have passed. Returns (count, elapsed)."""
    count, start = 0, time.perf_counter()
    while (count < reps) if reps else (time.perf_counter() - start < seconds):
        step()
        count += 1
    return count, time.perf_counter() - start


def python_matmul(n):
    a = [[(i * n + j) % 7 / 7 for j in range(n)] for i in range(n)]
    bt = list(zip(*[[(i + 2 * j) % 5 / 5 for j in range(n)] for i in range(n)]))
    out = {}

    def step():
        out["c"] = [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]
    return step, lambda: sum(map(sum, out["c"]))


def numpy_matmul(n):
    import numpy as np
    i, j = np.indices((n, n))
    a, b = (i * n + j) % 7 / 7, (i + 2 * j) % 5 / 5
    out = {}

    def step():
        out["c"] = a @ b
    return step, lambda: float(out["c"].sum())


def torch_matmul(n, device):
    import torch
    available = {"cpu": True, "cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available(),
                 "xpu": hasattr(torch, "xpu") and torch.xpu.is_available()}
    if not available.get(device):
        ok = ", ".join(d for d, a in available.items() if a)
        raise SystemExit(f"torch device '{device}' is not available on this machine (available: {ok})")
    sync = {"cuda": torch.cuda.synchronize, "mps": torch.mps.synchronize}.get(device)
    if device == "xpu":
        sync = torch.xpu.synchronize
    gen = torch.Generator().manual_seed(0)
    a = torch.rand(n, n, generator=gen).to(device)
    b = torch.rand(n, n, generator=gen).to(device)
    out = {"c": a @ b}  # warm-up: load kernels before timing
    if sync:
        sync()

    def step():
        out["c"] = a @ b
        if sync:
            sync()  # GPUs run asynchronously; wait so the clock and count are honest
    return step, lambda: float(out["c"].sum().item())


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("task", choices=["idle", "python-matmul", "numpy-matmul", "torch-matmul"])
    p.add_argument("--seconds", type=float, default=30, help="run length (default 30)")
    p.add_argument("--reps", type=int, help="do exactly this many multiplications instead")
    p.add_argument("--n", type=int, help="matrix size (default 120, or 2048 for torch)")
    p.add_argument("--device", default="cpu", help="torch device: cpu, mps, cuda, xpu")
    args = p.parse_args()
    n = args.n or (2048 if args.task == "torch-matmul" else 120)

    if args.task == "idle":
        start = time.perf_counter()
        time.sleep(args.seconds)
        count, elapsed, checksum = 0, time.perf_counter() - start, 0.0
    else:
        step, check = {"python-matmul": lambda: python_matmul(n),
                       "numpy-matmul": lambda: numpy_matmul(n),
                       "torch-matmul": lambda: torch_matmul(n, args.device)}[args.task]()
        count, elapsed = repeat(step, args.seconds, args.reps)
        checksum = check()

    print(json.dumps({
        "task": args.task, "device": args.device if args.task == "torch-matmul" else "cpu",
        "n": n, "reps": count, "work_seconds": round(elapsed, 3),
        "gflops": round(2 * n ** 3 * count / elapsed / 1e9, 2) if count else 0,
        "checksum": round(checksum, 1), "machine": platform.machine()}))


if __name__ == "__main__":
    main()
