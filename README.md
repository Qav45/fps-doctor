# FPS Doctor v1.0.0

Windows PC performance diagnostic tool. Identifies FPS-killing processes, bottlenecks, misconfigured settings, driver issues, and thermal problems — then generates a prioritized report with a health score.

## Requirements

- Windows 10 or 11
- Python 3.10 or later — [download from python.org](https://www.python.org/downloads/) if needed
- Run your terminal **as Administrator** for full results (right-click → "Run as administrator")

## Installation

### Option A — Install from the wheel (recommended, no git needed) **(OUTDATED DO NOT USE)**

Download `fps_doctor-1.0.0-py3-none-any.whl` from the [v1.0.0 release](https://github.com/Qav45/fps-doctor/releases/tag/v1.0.0), then:
 **(OUTDATED DO NOT USE)**
```
pip install fps_doctor-1.0.0-py3-none-any.whl
fps-doctor
```
 **(OUTDATED DO NOT USE)**
That's it. The `fps-doctor` command is now on your PATH.

### Option B — Clone and run

```
git clone https://github.com/Qav45/fps-doctor.git
cd fps-doctor
pip install -r requirements.txt
python main.py
```

### Option C — Editable install (for development)

```
git clone https://github.com/Qav45/fps-doctor.git
cd fps-doctor
pip install -e .
fps-doctor
```

Changes you make to the source are reflected immediately without reinstalling.

> **Tip:** If `pip` is not recognised, try `python -m pip install ...` instead.  
> **Tip:** If you get WMI or registry errors, make sure the terminal is running as Administrator.

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

# Also write a structured JSON report
python main.py --json

# Skip monitoring entirely
python main.py --duration 0
```

## What It Checks

**Phase 1 — System Specs:** CPU, GPU, RAM, storage, motherboard, BIOS, OS, displays, network.

**Phase 2 — FPS Diagnosis (16 sections):**
- Driver age and Device Manager errors
- Background FPS-killing processes (40+ known)
- Thermal throttling and power plan alignment
- Memory and pagefile usage
- Disk space, TRIM, and sequential speed
- Network latency and throttling
- Software overlays (Discord, Steam, Xbox Game Bar, etc.)
- Windows settings (Game Mode, HAGS, visual effects, animations)
- GPU settings (HAGS, G-Sync registry hints)
- DirectX and runtime versions
- BIOS firmware (XMP/DOCP, Resizable BAR, Secure Boot)
- Display refresh rate and multi-monitor
- Startup programs
- DPC latency snapshot
- Problematic services
- Event log errors (WHEA, display driver crashes, Kernel-Power)

**Phase 3 — Bottleneck Analysis:** Live 5-second sample to identify CPU/GPU/RAM/VRAM/thermal/storage/power/single-thread bottlenecks.

**Phase 4 — Settings Audit:** ~21 settings checked with current value, verdict (optimal/suboptimal/problematic), and an actionable fix for each.

**Phase 5 — Live Monitoring:** Continuous 1-sample/sec tracking with a Rich live table. Detects spikes and thermal throttle events.

**Phase 6 — Report:** Timestamped `.txt` (and optional `.json`) report with all findings, statistics, a health score, and prioritized recommendations.

## Output

A timestamped report (`fps_doctor_report_YYYYMMDD_HHMMSS.txt`) is written to the project folder unless `--output` is set. All findings print to the terminal with color coding via Rich, ending with a health score and letter grade.

## Limitations

- Windows only — no macOS or Linux support.
- Reads and recommends only — it does not change settings or install drivers.
- GPU metrics depend on GPUtil; hybrid/laptop GPUs may show incomplete data.

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Links

- [Wiki / full documentation](WIKI.md)
- [GitHub](https://github.com/Qav45/fps-doctor)
