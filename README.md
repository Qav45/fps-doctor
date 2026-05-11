# FPS Doctor v1.0.0

Windows PC performance diagnostic tool. Identifies FPS-killing processes, bottlenecks, misconfigured settings, driver issues, and thermal problems.

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges recommended

## Installation

```
pip install -r requirements.txt
```

## Usage

```
# Interactive (prompts for monitoring duration)
python main.py

# Skip monitoring phase
python main.py --no-monitor

# Set monitoring duration directly (minutes)
python main.py --duration 5

# Custom report output path
python main.py --output C:\Users\you\report.txt

# Skip monitoring entirely
python main.py --duration 0
```

## What It Checks

**Phase 1 — System Specs:** CPU, GPU, RAM, storage, motherboard, OS, display, network.

**Phase 2 — FPS Diagnosis (12 sections):**
- Driver age and errors
- Background FPS-killing processes (40+ known)
- Thermal throttling and power plan
- Memory and pagefile usage
- Disk space and TRIM status
- Network latency and throttling
- Software overlays (Discord, Steam, Xbox Game Bar, etc.)
- Windows settings (Game Mode, HAGS, visual effects, animations)
- GPU settings (HAGS, G-Sync)
- DirectX and runtime versions
- BIOS firmware (XMP/DOCP, Resizable BAR, Secure Boot)
- Display refresh rate and multi-monitor

**Phase 3 — Bottleneck Analysis:** Live 5-second sample to identify CPU/GPU/RAM/VRAM/thermal/storage/power/single-thread bottlenecks.

**Phase 4 — Settings Audit:** 17 settings checked with current value, verdict (optimal/suboptimal/problematic), and actionable fix.

**Phase 5 — Live Monitoring:** Continuous sampling with live Rich display. Detects spikes and thermal throttle events.

**Phase 6 — Report:** Full text report with all findings, statistics, and prioritized recommendations.

## Output

A timestamped `.txt` report is written to the `fps-doctor/` directory. All findings are printed to the terminal with color coding via Rich.
