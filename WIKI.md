# FPS Doctor — Wiki

**Repository:** [https://github.com/Qav45/fps-doctor](https://github.com/Qav45/fps-doctor)

FPS Doctor is a **Windows-only**, **command-line** PC performance diagnostic. It gathers hardware and OS facts, runs many automated checks related to gaming FPS and stutter, samples live performance briefly (and optionally for a longer session), then writes a **text report** (and optionally **JSON**) with prioritized recommendations and a **health score**.

This page describes **what you can do with the tool**, **what each phase checks**, and **how long a typical run takes**.

---

## Requirements

| Item | Notes |
|------|--------|
| **OS** | Windows 10 or 11 |
| **Python** | 3.9+ (`setup.py`); README suggests 3.10+ — use 3.10+ if you hit edge-case issues |
| **Privileges** | **Administrator** recommended; without admin, some WMI/registry reads may be incomplete |
| **GPU metrics** | `GPUtil` is used for GPU load/temperature in bottleneck and live monitoring; if it fails, GPU fields may show as unavailable |

**Dependencies:** `psutil`, `WMI`, `GPUtil`, `rich`, `pywin32` (see `requirements.txt`).

---

## Installation

From the cloned repository:

```bash
pip install -r requirements.txt
```

Optional: install as a package so the `fps-doctor` command is on your PATH:

```bash
pip install -e .
```

Then you can run `fps-doctor` instead of `python main.py`.

---

## What you can do (capabilities overview)

1. **Inventory your PC** — CPU, GPU, RAM, storage, motherboard, BIOS, OS, displays, network basics (via WMI and system APIs).
2. **FPS-oriented diagnosis** — 16 themed sections (drivers, background apps, thermals, memory, disk, network, overlays, Windows/GPU settings, DirectX, BIOS hints, display, startup, DPC rate, services, event log).
3. **Quick bottleneck snapshot** — ~5 seconds of CPU/GPU/RAM (and more) sampling, interpreted as CPU/GPU/RAM/VRAM/thermal/storage/power/single-thread/software-style findings.
4. **Settings audit** — ~21 registry/power/network items with a verdict: optimal / suboptimal / problematic, each with a short fix hint.
5. **Optional live monitoring** — Your chosen duration (default **10 minutes** if interactive), **1 sample per second**, Rich live table; tracks spikes and throttle-related patterns for the report.
6. **Reports** — Timestamped **`fps_doctor_report_YYYYMMDD_HHMMSS.txt`** in the project folder (unless you pass `--output`). Optional **`--json`** for machine-readable export.
7. **Terminal UX** — Banner, phased progress, color-coded summary table of critical/warning items, and a **health score / letter grade** at the end.

**What it does *not* do:** change settings, install drivers, or fix problems automatically — it **reads** and **recommends** only.

---

## Command-line reference

| Flag | Effect |
|------|--------|
| *(no flags)* | Full run; **prompts** for Phase 5 duration (minutes); default **10** if you press Enter |
| `--duration N` | Phase 5 length in **minutes** (e.g. `--duration 5`). **`0`** skips live monitoring |
| `--no-monitor` | Skips Phase 5 entirely (no prompt) |
| `--output PATH` | Write the text report to **PATH** (JSON name is derived by replacing `.txt` with `.json` when `--json` is used) |
| `--json` | Also writes a structured **JSON** report next to the text report |
| `--no-benchmark` | Documented in `--help` as skipping a disk I/O benchmark; **as of v1.1.0 this flag is not yet wired in `main.py`**, so the small sequential disk test inside diagnosis may still run |

**Tip:** For a **fast** audit: `python main.py --no-monitor` (or `--duration 0` without `--no-monitor` — you still get the duration prompt unless you pass `--duration 0`).

**Tip:** For **actionable** bottleneck data, start a game or benchmark **during** Phase 5 (`--duration 5` etc.).

---

## Phase-by-phase: what runs and what it means

### Phase 1 — System specifications

Collects a structured snapshot: CPU (name, cores, clocks, cache), GPU(s), VRAM, driver info, RAM capacity/speed/channels, each volume’s model/type/size/free/health where available, motherboard and BIOS version/date, OS edition/build, power plan summary, display(s), network adapters.

**Use:** baseline context for every later section and the written report.

---

### Phase 2 — FPS loss diagnosis (16 sections)

| # | Section key | What it roughly covers |
|---|-------------|-------------------------|
| 1 | `driver_issues` | GPU driver **age**, known-bad version **notes**, chipset driver read, **Device Manager** error devices, generic **Microsoft** drivers on important device classes |
| 2 | `background_processes` | Scans running processes against **40+** known “FPS killer” names (`known_issues.py`), CPU from background, etc. |
| 3 | `thermal_power` | Thermals/power throttling signals, power plan alignment with gaming |
| 4 | `memory_issues` | RAM pressure, pagefile behavior, hardware-reserved memory hints |
| 5 | `storage_issues` | Free space per drive, **16 MB** temp-file sequential read/write speed, **TRIM** query, BitLocker/other storage-related flags |
| 6 | `network_issues` | Latency/throttling-related checks useful for online games |
| 7 | `software_overlays` | Discord, Steam, Xbox Game Bar, capture tools, etc. (process/registry oriented) |
| 8 | `windows_settings` | Game Mode, Game DVR, visual effects, animations, indexing, etc. |
| 9 | `gpu_settings` | e.g. **HAGS**, G-Sync-related registry hints where applicable |
| 10 | `directx_runtimes` | DirectX / VC++ runtime presence signals |
| 11 | `bios_firmware` | BIOS date and **feature hints** (XMP/DOCP, Resizable BAR, Secure Boot — advisory) |
| 12 | `display_issues` | Refresh rate, multi-monitor pitfalls |
| 13 | `startup_programs` | Startup footprint that can steal CPU/disk in-game |
| 14 | `dpc_latency` | WMI performance counter **DPC rate** snapshot (high DPC → stutter/audio glitch driver suspects) |
| 15 | `problematic_services` | Running services matched against a **curated list** in `known_issues.py` |
| 16 | `event_log_errors` | **WHEA** hardware errors, **Display** driver crash events, **Kernel-Power** unexpected shutdown events (via `wevtutil`) |

Sections run with internal parallelism where coded (e.g. event log queries).

---

### Phase 3 — Bottleneck analysis (~5 seconds)

Takes a **short live sample** (CPU overall and per-core, RAM %, pagefile %, GPU load/temp/VRAM% if GPUtil works), then **classifies** likely bottlenecks: CPU vs GPU bound, RAM/pagefile pressure, VRAM pressure, thermals, disk activity spike, power plan, single-thread skew, “software CPU overhead” from top processes.

**Use:** quick “what is limiting me **right now**” — run while your typical load is active for more meaningful numbers.

---

### Phase 4 — Settings audit (~21 checks)

Each item includes **category**, **setting name**, **current value**, **verdict**, and **recommendation**. Topics include:

- Power plan (High Performance vs Balanced vs Power Saver)
- **HAGS** (registry)
- **Game Mode**, **Game DVR / captures**
- Visual effects, transparency, animations
- Core isolation / memory integrity (gaming impact)
- **SysMain** (Superfetch), **Windows Search**
- Processor minimum/maximum state
- **Nagle** / **network throttling** registry hints
- Pagefile on system drive vs dedicated
- USB selective suspend
- Full-screen optimizations
- Notifications
- **Timer resolution** (NtQueryTimerResolution)
- **Delivery Optimization** (P2P update sharing modes)
- **DirectX shader cache** folder presence

**Use:** a checklist of common Windows misconfigurations for latency and FPS.

---

### Phase 5 — Live monitoring (optional)

- **Sample interval:** 1 second  
- **Metrics:** CPU (total + per-core), CPU freq, CPU temp (if `psutil` exposes sensors), GPU %/temp/clock/VRAM (if GPUtil works), RAM %, disk read/write MB/s, network up/down, top CPU and RAM processes  
- **Detection:** spike detection and thermal-throttle-oriented event counting for the report  
- **UI:** Rich `Live` table while running  
- **Interrupt:** `Ctrl+C` skips the rest of monitoring but **continues** to Phase 6 report

**Use:** correlate stutters with CPU/GPU/disk/network spikes during **real** gameplay.

---

### Phase 6 — Report and scoring

- **Text report:** full narrative with system specs, all diagnosis sections, bottlenecks, settings audit, monitoring stats, and recommendations.  
- **`--json`:** structured dump for spreadsheets, your own tooling, or sharing to developers.  
- **Health score:** numeric score out of 100 plus a **letter grade**, printed in a panel after the report path.  
- **Critical findings summary:** Rich table of critical/warning diagnosis lines, medium+ bottlenecks, and problematic settings.

---

## How long does it take?

Times are **approximate** and depend on CPU speed, disk speed, number of drives, WMI latency, and antivirus scanning the temp file during the small disk benchmark.

| Scenario | Phase 1–4 + 6 (fixed) | Phase 5 (your choice) | Typical total |
|----------|------------------------|------------------------|----------------|
| **Full default** (interactive, Enter for 10 min monitor) | ~**2–6 min** | **10 min** | ~**12–16 min** |
| **Quick audit** (`--no-monitor`) | ~**2–6 min** | 0 | ~**2–6 min** |
| **Short monitor** (`--duration 2`) | ~**2–6 min** | **2 min** | ~**4–8 min** |
| **Deep session** (`--duration 30`) | ~**2–6 min** | **30 min** | ~**32–36 min** |

**Within the fixed block:**

| Phase | Approx. duration | Dominant cost |
|-------|------------------|----------------|
| 1 — System specs | ~10–60 s | WMI / disk enumeration |
| 2 — FPS diagnosis | ~**1–4 min** | Many checks + disk test + event log subprocesses |
| 3 — Bottleneck | ~**5–8 s** | Fixed sampling window + 1 s priming |
| 4 — Settings audit | ~**1–10 s** | Registry / powercfg |
| 6 — Report | ~**1–3 s** | File I/O + formatting |

**Rule of thumb:** budget **~5 minutes** for a no-monitoring run on a modern PC; budget **monitoring duration + ~5 minutes** when monitoring is enabled.

---

## Suggested workflows

| Goal | Command idea |
|------|----------------|
| First-time full health pass | `python main.py` (admin), run a game during monitoring |
| Laptop on battery / time constrained | `python main.py --no-monitor` |
| CI / scripted snapshot | `python main.py --no-monitor --json --output D:\reports\run.txt` |
| Compare before/after a change | Same flags twice; diff the `.txt` or `.json` files |

---

## Limitations and caveats

- **Windows only** — no macOS/Linux support.  
- **Heuristics, not guarantees** — “warning” does not always mean you must change something; “ok” does not prove stability in every game.  
- **GPU stats** depend on driver and GPUtil; laptops with hybrid graphics can look confusing.  
- **DPC / event log** checks are useful pointers; dedicated tools (e.g. LatencyMon) may still be needed for driver-level debugging.  
- **BIOS features** (XMP, ReBAR) are often **read-advisory**; exact capability depends on WMI/BIOS reporting.

---

## Publishing this as a GitHub Wiki

GitHub Wikis are a separate tab on the repo. You can:

1. Enable the Wiki in the repository **Settings** (if disabled).  
2. Create a **Home** page and paste sections from this file, or  
3. Commit this file as **`WIKI.md`** in the repo (as here) and link it from the README for users who prefer in-repo docs.

---

*Document generated to match FPS Doctor **v1.0.0** behavior in the codebase. If the project changes, update phase counts and flags against `main.py` and the collectors.*
