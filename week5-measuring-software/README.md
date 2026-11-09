# Measuring Software Energy Consumption

The goal of this lab is to learn how to measure the energy used by running a piece of
software, and to see how much the *way* software is written, and *where* it runs (CPU or
GPU), changes that energy. You can do it on your own laptop: Apple Silicon Mac, Windows or
Linux, Intel or AMD.

## Background: what can your computer tell you?

No computer measures "the energy of my program" directly. You will use a **meter** that reports
power for some part of the machine, and you must say which part it covers:

| Your machine | Meter (`--meter`) | What it covers | Notes |
|--------------|-------------------|----------------|-------|
| Mac with Apple Silicon (M1–M5) | `macmon` (default) | CPU + GPU + Neural Engine (the "SoC") | Install with `brew install macmon`. No sudo needed. |
| Linux, Intel or AMD | `rapl` (default) | CPU package | Needs `sudo` (see below). Not available in VMs, WSL or containers. |
| Windows 11, Intel or AMD | `codecarbon` (default) | CPU | Uses real counters when Windows provides them, otherwise an **estimate**. Check the `mode` column. |
| Any laptop | `battery` | The whole laptop, including the screen | Only on battery power: unplug the charger. Less precise, so use 30 s+ runs. |
| Linux with an NVIDIA GPU | `rapl+nvidia` | CPU package + GPU board | For Part B. Needs `sudo` like `rapl`. `rapl` alone does **not** see the GPU. |
| Any machine with an NVIDIA GPU | `nvidia` | GPU board only | From the NVIDIA driver; no sudo needed. |

Some meters **measure** and some **estimate**. CodeCarbon, for example, falls back to estimating
power from the CPU model and load when it can't read a counter. Part of this lab is finding out
which you have.

## Taking good measurements

1. **Isolation:** close other applications (browser, video calls, cloud sync). Keep the laptop on
   the same power setting for all runs.
2. **Baseline:** measure the machine doing nothing (`idle`), so you can tell how much extra
   energy your program used.
3. **Long enough runs:** each run lasts 30 s, because meters sample about once a second.
   The workload counts how much work it completed in that time.
4. **Repeats:** run each test **5 times**, alternating between tests rather than doing all
   runs of one test together. Report every run, the mean and the standard deviation.
5. **Warm-up:** do one unmeasured run first; the first run loads libraries and is slower.
6. **Limits:** write down what your meter cannot see.

## Task

Time available: 1 hour. In the `week5-measuring-software` folder, create
`username-week5-labnotes.md`.

### 1. Set up

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On Linux without an NVIDIA GPU, install the smaller CPU-only PyTorch first:
`pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu`.

Check that everything runs, without measuring yet:

```bash
python workload.py numpy-matmul --seconds 5
```

### 2. Choose your meter

Run a short idle test with the default meter for your machine:

```bash
python measure.py --label idle -- python workload.py idle --seconds 10
```

On Linux, RAPL needs root, so use your environment's Python explicitly:

```bash
sudo "$(which python)" measure.py --label idle -- "$(which python)" workload.py idle --seconds 10
```

`measure.py` prints the energy and adds a row to `runs.csv`. Look at the `scope` and `mode`
columns: what does your meter measure, and is it a measurement or an estimate?

### 3. Part A – Does the way software is written matter? (everyone)

The same matrix multiplication, written as pure Python loops and with NumPy. Run each 5 times,
alternating, plus 5 idle runs:

```bash
python measure.py --label idle   -- python workload.py idle
python measure.py --label python -- python workload.py python-matmul
python measure.py --label numpy  -- python workload.py numpy-matmul
```

Sudo on Linux:

```bash
sudo "$(which python)" measure.py --label idle   -- sudo "$(which python)" workload.py idle
sudo "$(which python)" measure.py --label python -- sudo "$(which python)" workload.py python-matmul
sudo "$(which python)" measure.py --label numpy  -- sudo "$(which python)" workload.py numpy-matmul
```

### 4. Part B – Does offloading to the GPU help? (if you have a GPU)

Use `mps` on an Apple Silicon Mac, `cuda` with an NVIDIA GPU, `xpu` with a supported Intel GPU:

```bash
python measure.py --label torch-cpu -- python workload.py torch-matmul --device cpu
python measure.py --label torch-gpu -- python workload.py torch-matmul --device mps
```

On a Mac, `macmon` already covers both CPU and GPU. With an NVIDIA GPU, a CPU meter misses the
GPU entirely, so measure Part B (including an idle run) with both:

```bash
sudo "$(which python)" measure.py --meter rapl+nvidia --gpus 0 --label idle      -- "$(which python)" workload.py idle
sudo "$(which python)" measure.py --meter rapl+nvidia --gpus 0 --label torch-cpu -- "$(which python)" workload.py torch-matmul --device cpu
sudo "$(which python)" measure.py --meter rapl+nvidia --gpus 0 --label torch-gpu -- "$(which python)" workload.py torch-matmul --device cuda
```

`--gpus 0` measures only the GPU the workload uses (`nvidia-smi` lists them). On a shared
machine, check with `nvidia-smi` that nobody else is using that GPU. On Windows, use
`--meter nvidia` for the GPU and `--meter codecarbon` for the CPU, and add the two.

No GPU? Pair up with someone who has one, or skip to Part C.

### 5. Part C – Do two meters agree?

Repeat Part A with a second meter: `--meter battery` (unplug the charger) or `--meter codecarbon`.
The meters cover different parts of the machine, so they *should* disagree. Your job is to
explain by how much and why.

CodeCarbon meter:

```bash
python measure.py --label idle --meter codecarbon -- python workload.py idle
python measure.py --label python --meter codecarbon -- python workload.py python-matmul
python measure.py --label numpy --meter codecarbon  -- python workload.py numpy-matmul
```

Battery meter:

```bash
python measure.py --label idle --meter battery -- python workload.py idle
python measure.py --label python --meter battery -- python workload.py python-matmul
python measure.py --label numpy --meter battery  -- python workload.py numpy-matmul
```

### 6. Analyse and write up

```bash
python analyse.py runs.csv --baseline python
```

This prints markdown tables of every run, the means and SDs, and the **energy per GFLOP**
(1 GFLOP = one billion floating-point operations): energy divided by work done. Use it as the
fair comparison, because the tests do very different amounts of work in 30 s.

Your report needs:

1. **Introduction and method:** what you measured, on which machine (model, CPU, OS), with which
   meter(s), and how you kept measurements clean.
2. **A subsection per test:** goal, the exact command, the results table.
3. **Worked example:** calculate one row by hand. *P* = *E* / *t* (watts = joules ÷ seconds);
   1 Wh = 3 600 J; energy above idle = *E* − *P*(idle) × *t*.
4. **Comparison:** how much less energy per GFLOP did NumPy (and the GPU, if you had one) use? Was
   that because power went down, or because the work finished faster?
5. **Scaling up:** suppose your machine has to do 100 TFLOP (100 000 GFLOP) of this work per year.
   How many kWh would each version need, and how long would it run?
6. **`## Reflections`:** what surprised you, how the two meters compared, which meter you trust and
   why, and what none of them can see (the screen? memory? the network? the charger?).

Commit and push your notes **and** `runs.csv`.

## Learning outcomes

- You can take repeatable software energy measurements and report them with mean, SD and a method.
- You understand that energy = power × time, so faster software usually saves energy even when its
  power is higher.
- You can estimate how much energy better code or a GPU saves, and scale it up to a year.
- You know that different meters measure different parts of the system, and the difference
  between a measurement and an estimate.

## Starting points

- [macmon](https://github.com/vladkens/macmon) – power monitor for Apple Silicon
- [CodeCarbon methodology](https://docs.codecarbon.io/latest/explanation/methodology/) – how it measures or estimates
- [RAPL in CodeCarbon's docs](https://docs.codecarbon.io/latest/explanation/rapl/) – what the Linux counters cover
- [Python virtual environments](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/)

## Acknowledgement

This lab exercise is made based on the materials from the Sustainable Computing course held by
Adrian Friday, a Professor of Computing and Sustainability at Lancaster University.
