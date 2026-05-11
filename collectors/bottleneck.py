"""Phase 3: Bottleneck analysis."""

import time

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import GPUtil
    GPUTIL_OK = True
except ImportError:
    GPUTIL_OK = False


def _finding(btype, severity, description, recommendation):
    return {
        "type": btype,
        "severity": severity,
        "description": description,
        "recommendation": recommendation,
    }


def _sample_live(duration=5):
    """Poll CPU/GPU/RAM usage for `duration` seconds, return averages."""
    if not PSUTIL_OK:
        return {}

    samples = []
    try:
        # Prime psutil cpu_percent (first call always returns 0)
        psutil.cpu_percent(interval=None)
        time.sleep(1)

        for _ in range(max(1, duration - 1)):
            sample = {}
            try:
                sample["cpu_total"] = psutil.cpu_percent(interval=1)
                sample["cpu_per_core"] = psutil.cpu_percent(interval=None, percpu=True)
                sample["ram_pct"] = psutil.virtual_memory().percent

                freq = psutil.cpu_freq()
                sample["cpu_freq"] = freq.current if freq else None

                try:
                    swap = psutil.swap_memory()
                    sample["pagefile_pct"] = swap.percent
                except Exception:
                    sample["pagefile_pct"] = 0

                # GPU
                if GPUTIL_OK:
                    try:
                        gpus = GPUtil.getGPUs()
                        if gpus:
                            g = gpus[0]
                            sample["gpu_load"] = g.load * 100
                            sample["gpu_temp"] = g.temperature
                            sample["gpu_mem_pct"] = (g.memoryUsed / g.memoryTotal * 100) if g.memoryTotal else 0
                        else:
                            sample["gpu_load"] = None
                            sample["gpu_temp"] = None
                            sample["gpu_mem_pct"] = None
                    except Exception:
                        sample["gpu_load"] = None
                        sample["gpu_temp"] = None
                        sample["gpu_mem_pct"] = None
                else:
                    sample["gpu_load"] = None
                    sample["gpu_temp"] = None
                    sample["gpu_mem_pct"] = None

                samples.append(sample)
            except Exception:
                pass
    except Exception:
        pass

    if not samples:
        return {}

    def avg(key):
        vals = [s[key] for s in samples if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    result = {
        "cpu_total": avg("cpu_total"),
        "ram_pct": avg("ram_pct"),
        "swap_pct": avg("pagefile_pct"),
        "cpu_freq": avg("cpu_freq"),
        "gpu_load": avg("gpu_load"),
        "gpu_temp": avg("gpu_temp"),
        "gpu_mem_pct": avg("gpu_mem_pct"),
        "cpu_per_core": [],
    }

    # Average per-core usage
    if samples and "cpu_per_core" in samples[0]:
        n_cores = len(samples[0]["cpu_per_core"])
        for c in range(n_cores):
            core_vals = [s["cpu_per_core"][c] for s in samples if "cpu_per_core" in s and len(s["cpu_per_core"]) > c]
            result["cpu_per_core"].append(sum(core_vals) / len(core_vals) if core_vals else 0)

    return result


def analyze_bottlenecks(system_specs, live_sample=None):
    """
    Analyze collected data to identify bottlenecks.
    Takes system_specs and an optional live sample.
    Returns list of bottleneck findings.
    """
    findings = []

    if live_sample is None:
        live_sample = {}

    cpu_pct = live_sample.get("cpu_total")
    gpu_pct = live_sample.get("gpu_load")
    ram_pct = live_sample.get("ram_pct")
    swap_pct = live_sample.get("swap_pct")
    gpu_temp = live_sample.get("gpu_temp")
    gpu_mem_pct = live_sample.get("gpu_mem_pct")
    cpu_freq = live_sample.get("cpu_freq")
    cpu_per_core = live_sample.get("cpu_per_core", [])

    # ── CPU Bottleneck ──────────────────────────────────────────────────────
    if cpu_pct is not None and gpu_pct is not None:
        if cpu_pct > 90 and gpu_pct < 80:
            findings.append(_finding(
                "CPU Bottleneck", "high",
                f"CPU usage is {cpu_pct:.1f}% while GPU is only {gpu_pct:.1f}%. CPU cannot feed frames to GPU fast enough.",
                "Upgrade CPU, reduce CPU-heavy settings (simulation distance, AI count), or overclock CPU if thermal headroom allows."
            ))
        elif cpu_pct > 75 and (gpu_pct is None or gpu_pct < 70):
            findings.append(_finding(
                "CPU Bottleneck", "medium",
                f"CPU usage at {cpu_pct:.1f}% with GPU at {f'{gpu_pct:.1f}' if gpu_pct is not None else 'N/A'}%. Some CPU pressure detected.",
                "Close background applications, disable CPU-intensive overlays, ensure High Performance power plan."
            ))
    elif cpu_pct is not None and cpu_pct > 90:
        findings.append(_finding(
            "CPU Bottleneck", "medium",
            f"CPU usage is very high at {cpu_pct:.1f}%. GPU data unavailable for comparison.",
            "High CPU usage may indicate a CPU bottleneck. Close background applications."
        ))

    # ── GPU Bottleneck ──────────────────────────────────────────────────────
    if gpu_pct is not None:
        if gpu_pct > 95:
            if cpu_pct is not None and cpu_pct < 70:
                findings.append(_finding(
                    "GPU Bottleneck", "high",
                    f"GPU usage is {gpu_pct:.1f}% while CPU is only {cpu_pct:.1f}%. GPU is the limiting factor.",
                    "Reduce GPU-intensive settings: resolution, anti-aliasing, shadows, texture quality, ray tracing."
                ))
            else:
                findings.append(_finding(
                    "GPU Bottleneck", "medium",
                    f"GPU usage at {gpu_pct:.1f}%. GPU is working at capacity.",
                    "Reduce graphical settings or upgrade GPU. Ensure GPU drivers are up to date."
                ))
    else:
        findings.append(_finding(
            "GPU Data Unavailable", "low",
            "Could not sample GPU usage. GPUtil may not be available or GPU is not detected.",
            "Install GPUtil (pip install gputil) for GPU usage monitoring."
        ))

    # ── RAM Bottleneck ──────────────────────────────────────────────────────
    if ram_pct is not None:
        if ram_pct > 90:
            findings.append(_finding(
                "RAM Bottleneck", "high",
                f"RAM usage at {ram_pct:.1f}%. System is nearly out of physical memory.",
                "Close background applications immediately. Consider upgrading RAM if this occurs during gaming."
            ))
        elif ram_pct > 80:
            findings.append(_finding(
                "RAM Bottleneck", "medium",
                f"RAM usage at {ram_pct:.1f}%. High memory pressure.",
                "Close unused applications. 16GB is recommended minimum for modern games; 32GB for content creation."
            ))

    if swap_pct is not None and swap_pct > 30:
        findings.append(_finding(
            "Pagefile Usage", "high",
            f"Pagefile usage at {swap_pct:.1f}%. Windows is using disk as RAM.",
            "This causes severe stuttering. Add more RAM or close background applications aggressively."
        ))

    # ── VRAM Bottleneck ─────────────────────────────────────────────────────
    if gpu_mem_pct is not None:
        if gpu_mem_pct > 95:
            findings.append(_finding(
                "VRAM Bottleneck", "high",
                f"VRAM usage at {gpu_mem_pct:.1f}%. GPU memory is nearly full.",
                "Reduce texture quality, lower resolution, or disable VRAM-heavy features like ray tracing."
            ))
        elif gpu_mem_pct > 85:
            findings.append(_finding(
                "VRAM Pressure", "medium",
                f"VRAM usage at {gpu_mem_pct:.1f}%. Approaching VRAM limit.",
                "Monitor VRAM usage in games. Reduce texture quality if stuttering occurs."
            ))

    # ── Thermal Bottleneck ──────────────────────────────────────────────────
    if gpu_temp is not None:
        if gpu_temp > 90:
            findings.append(_finding(
                "GPU Thermal Throttle", "high",
                f"GPU temperature at {gpu_temp}°C. Likely thermal throttling.",
                "Improve case airflow, clean GPU heatsink/fans, check thermal pad condition, increase fan curve."
            ))
        elif gpu_temp > 83:
            findings.append(_finding(
                "GPU Running Hot", "medium",
                f"GPU temperature at {gpu_temp}°C. Approaching throttle threshold.",
                "Increase GPU fan speed or improve case airflow to prevent thermal throttling."
            ))

    # Check CPU temp from psutil if available
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if temps:
            for chip, entries in temps.items():
                for entry in entries:
                    if "cpu" in chip.lower() or "core" in (entry.label or "").lower():
                        if entry.current > 95:
                            findings.append(_finding(
                                "CPU Thermal Throttle", "high",
                                f"CPU temperature at {entry.current}°C. Critical - thermal throttling active.",
                                "Immediately check CPU cooler, thermal paste, and case airflow. This will cause severe FPS drops."
                            ))
                        elif entry.current > 85:
                            findings.append(_finding(
                                "CPU Running Hot", "medium",
                                f"CPU temperature at {entry.current}°C.",
                                "Check CPU cooler mounting, thermal paste quality, and case airflow."
                            ))
                        break
    except Exception:
        pass

    # ── Storage Bottleneck ──────────────────────────────────────────────────
    if PSUTIL_OK:
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    pct_free = (usage.free / usage.total) * 100
                    if pct_free < 5:
                        findings.append(_finding(
                            "Storage Full", "high",
                            f"Drive {part.mountpoint} has only {pct_free:.1f}% free space.",
                            "Free up disk space immediately. Windows needs 10-15% free for pagefile and temp files."
                        ))
                except Exception:
                    pass
        except Exception:
            pass

        try:
            io1 = psutil.disk_io_counters()
            time.sleep(1)
            io2 = psutil.disk_io_counters()
            if io1 and io2:
                read_mb = (io2.read_bytes - io1.read_bytes) / (1024 * 1024)
                write_mb = (io2.write_bytes - io1.write_bytes) / (1024 * 1024)
                total_io = read_mb + write_mb
                if total_io > 200:
                    findings.append(_finding(
                        "High Disk I/O", "medium",
                        f"Disk I/O at {total_io:.1f}MB/s (read: {read_mb:.1f}, write: {write_mb:.1f}).",
                        "High background disk activity detected. Check for Windows Update, indexing, or cloud sync."
                    ))
        except Exception:
            pass

    # ── Network Bottleneck ──────────────────────────────────────────────────
    # (Ping results would come from diagnosis phase, apply here as finding)
    # We just flag if diagnosis already found issues - this is synthesized below via description

    # ── Power Bottleneck ────────────────────────────────────────────────────
    if system_specs:
        power_info = system_specs.get("power", {})
        plan_name = power_info.get("power_plan_name", "")
        HIGH_PERF_GUIDS = {"8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "e9a42b02-d5df-448d-aa00-03f14749eb61"}
        plan_guid = power_info.get("power_plan_guid", "").lower()
        if plan_guid and plan_guid not in HIGH_PERF_GUIDS:
            if "power saver" in plan_name.lower():
                findings.append(_finding(
                    "Power Plan Bottleneck", "high",
                    f"Power Saver plan active: '{plan_name}'. CPU frequencies are severely limited.",
                    "Switch to High Performance or Ultimate Performance power plan immediately."
                ))
            elif "balanced" in plan_name.lower():
                findings.append(_finding(
                    "Power Plan Bottleneck", "medium",
                    f"Balanced power plan active: '{plan_name}'. CPU may not boost to max clock consistently.",
                    "Switch to High Performance power plan for consistent CPU boost clock behavior."
                ))

    # ── Single-Thread Bottleneck ────────────────────────────────────────────
    if cpu_per_core:
        max_core = max(cpu_per_core)
        avg_core = sum(cpu_per_core) / len(cpu_per_core)
        if max_core > 90 and avg_core < 70:
            findings.append(_finding(
                "Single-Thread Bottleneck", "medium",
                f"One or more CPU cores at {max_core:.1f}% while average is {avg_core:.1f}%. Game may be single-thread limited.",
                "Single-thread bottlenecks require faster single-core CPU speed. Ensure XMP/DOCP is enabled and power plan is High Performance."
            ))

    # ── Software Bottleneck ─────────────────────────────────────────────────
    if PSUTIL_OK:
        try:
            # Sample background process CPU
            bg_cpu_total = 0.0
            game_like_procs = set()
            all_procs_cpu = []
            for proc in psutil.process_iter(["name", "cpu_percent", "pid"]):
                try:
                    pinfo = proc.info
                    cpu = pinfo.get("cpu_percent") or 0.0
                    name = pinfo.get("name") or ""
                    all_procs_cpu.append((name, cpu))
                    bg_cpu_total += cpu
                except Exception:
                    pass

            top_bg = sorted(all_procs_cpu, key=lambda x: x[1], reverse=True)[:5]
            if bg_cpu_total > 30:
                findings.append(_finding(
                    "Software CPU Overhead", "medium",
                    f"Background processes consuming ~{bg_cpu_total:.0f}% total CPU. Top: {', '.join(f'{n}({c:.0f}%)' for n, c in top_bg if c > 1)}",
                    "Close non-essential background applications while gaming."
                ))
        except Exception:
            pass

    return findings


def run_bottleneck_analysis(system_specs, duration=5):
    """Run live sampling then analyze bottlenecks. Returns list of findings."""
    live_sample = _sample_live(duration)
    return analyze_bottlenecks(system_specs, live_sample)
