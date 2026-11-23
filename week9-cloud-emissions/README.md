# Measuring Cloud Emissions

The goal for this lab excercise is to learn how to measure energy usage and understand hidden emissions when running software in a cloud environment such as Google Colab. On a virtual machine (VM), like the one our Colab notebook will be running on, you do not have access to low-level hardware counters such as Intel RAPL. Instead, we will rely on software-level measurements and approximate energy usage for CPU, GPU, and networking. Because cloud hardware is virtualised, these measurements we will take are estimates, and not exact ground-truth values. 

## How to make measurements on Colab

1. Avoid performing tasks that download data inside the measurement window. Uploads, downloads, and print-heavy output will skew energy readings.

2. Utilization and power logging runs in a Python thread. This adds a small but constant overhead, so repeat your tests and take the average.

3. Colab does not expose DRAM power, NVMe/SSD power, and CPU package components are not visible via utilisation. Take this into account when writing your report.

4. Repeat tests. Run each test 3 times, record all runs, report mean and standard deviation.

#### GPU measurements

Google Colab provides real-time GPU power readings using:

```
nvidia-smi --query-gpu=power.draw
```

This returns instantaneous power in watts. In the notebook we read the same values through NVIDIA's management library (`pynvml`): we sample the power repeatedly and integrate it over time, and for short runs we read the GPU's own energy counter. Both give energy in J or kWh.

#### CPU measurements

On the other hand, Colab does not expose CPU power, so we will estimate CPU energy using CPU utilisation and `psutil.cpu_percent()`. We will also estimate CPU power consumption based on the allocated CPU model and the share of the chip (number of vCPUs) your VM gets.

#### Carbon intensity

To turn energy into emissions, we use the yearly grid carbon intensity that Google publishes for each of its cloud regions ([region-carbon-info](https://github.com/GoogleCloudPlatform/region-carbon-info)); no registration is needed. Colab may put each session in a different region, so **write down the region your notebook ran in**.

## Task

Time available: 1.5 hours.

Make sure you have an up to date copy of your coursework repo available.  In the '`week9`' folder create a new markdown document called `username-week9-labnotes.md`. Upload Lab_09.ipynb from this repository to Google Colab. Run the script following the instructions and document your results in the markdown file.
