"""Phase 5: Live performance monitoring."""

import time
import datetime
import statistics

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

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    RICH_OK = True
except ImportError:
    RICH_OK = False


def _get_gpu_data():
    if not GPUTIL_OK:
        return None, None, None, None
    try:
        gpus = GPUtil.getGPUs()
        if gpus:
            g = gpus[0]
            return (
                round(g.load * 100, 1),
                g.temperature,
                round(g.clock) if g.clock else None,
                round(g.memoryUsed) if g.memoryUsed else None
            )
    except Exception:
        pass
    return None, None, None, None


def _get_cpu_temp():
    if not PSUTIL_OK:
        return None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for chip, entries in temps.items():
                for entry in entries:
                    if "cpu" in chip.lower() or "core" in (entry.label or "").lower():
                        return entry.current
    except Exception:
        pass
    return None


def _collect_sample(prev_disk_io, prev_net_io, prev_time):
    """Collect one performance sample."""
    sample = {
        "timestamp": datetime.datetime.now().isoformat(),
        "cpu_percent": None,
        "cpu_percent_per_core": [],
        "cpu_freq_mhz": None,
        "cpu_temp": None,
        "gpu_percent": None,
        "gpu_temp": None,
        "gpu_freq_mhz": None,
        "gpu_memory_used_mb": None,
        "ram_percent": None,
        "ram_used_gb": None,
        "disk_read_mbps": None,
        "disk_write_mbps": None,
        "net_sent_mbps": None,
        "net_recv_mbps": None,
        "top_cpu_procs": [],
        "top_ram_procs": [],
    }

    if not PSUTIL_OK:
        return sample, prev_disk_io, prev_net_io, prev_time

    try:
        sample["cpu_percent"] = psutil.cpu_percent(interval=None)
        sample["cpu_percent_per_core"] = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:
        pass

    try:
        freq = psutil.cpu_freq()
        if freq:
            sample["cpu_freq_mhz"] = round(freq.current, 1)
    except Exception:
        pass

    sample["cpu_temp"] = _get_cpu_temp()

    gpu_pct, gpu_temp, gpu_freq, gpu_mem = _get_gpu_data()
    sample["gpu_percent"] = gpu_pct
    sample["gpu_temp"] = gpu_temp
    sample["gpu_freq_mhz"] = gpu_freq
    sample["gpu_memory_used_mb"] = gpu_mem

    try:
        vm = psutil.virtual_memory()
        sample["ram_percent"] = vm.percent
        sample["ram_used_gb"] = round(vm.used / (1024 ** 3), 2)
    except Exception:
        pass

    # Disk I/O delta
    now = time.time()
    try:
        disk_io = psutil.disk_io_counters()
        elapsed = now - prev_time if prev_time else 1
        if disk_io and prev_disk_io and elapsed > 0:
            read_bytes = disk_io.read_bytes - prev_disk_io.read_bytes
            write_bytes = disk_io.write_bytes - prev_disk_io.write_bytes
            sample["disk_read_mbps"] = round(read_bytes / elapsed / (1024 * 1024), 2)
            sample["disk_write_mbps"] = round(write_bytes / elapsed / (1024 * 1024), 2)
        prev_disk_io = disk_io
    except Exception:
        pass

    # Network I/O delta
    try:
        net_io = psutil.net_io_counters()
        elapsed = now - prev_time if prev_time else 1
        if net_io and prev_net_io and elapsed > 0:
            sent_bytes = net_io.bytes_sent - prev_net_io.bytes_sent
            recv_bytes = net_io.bytes_recv - prev_net_io.bytes_recv
            sample["net_sent_mbps"] = round(sent_bytes / elapsed / (1024 * 1024), 3)
            sample["net_recv_mbps"] = round(recv_bytes / elapsed / (1024 * 1024), 3)
        prev_net_io = net_io
    except Exception:
        pass

    # Top processes
    try:
        procs = []
        for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_info"]):
            try:
                pinfo = proc.info
                procs.append({
                    "name": pinfo.get("name") or "",
                    "pid": pinfo.get("pid"),
                    "cpu_percent": pinfo.get("cpu_percent") or 0.0,
                    "ram_mb": (pinfo.get("memory_info").rss // (1024 * 1024)) if pinfo.get("memory_info") else 0,
                })
            except Exception:
                pass

        sample["top_cpu_procs"] = sorted(procs, key=lambda x: x["cpu_percent"], reverse=True)[:5]
        sample["top_ram_procs"] = sorted(procs, key=lambda x: x["ram_mb"], reverse=True)[:5]
    except Exception:
        pass

    return sample, prev_disk_io, prev_net_io, now


def _build_live_panel(sample, elapsed_s, total_s):
    """Build a rich renderable panel with current stats."""
    if not RICH_OK:
        return None

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", min_width=20)
    table.add_column(style="white", min_width=15)
    table.add_column(style="bold cyan", min_width=20)
    table.add_column(style="white", min_width=15)

    def fmt(val, unit="", decimals=1):
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:.{decimals}f}{unit}"
        return f"{val}{unit}"

    cpu_color = "red" if (sample.get("cpu_percent") or 0) > 85 else "yellow" if (sample.get("cpu_percent") or 0) > 60 else "green"
    gpu_color = "red" if (sample.get("gpu_percent") or 0) > 90 else "yellow" if (sample.get("gpu_percent") or 0) > 70 else "green"
    ram_color = "red" if (sample.get("ram_percent") or 0) > 85 else "yellow" if (sample.get("ram_percent") or 0) > 70 else "green"

    cpu_str = f"[{cpu_color}]{fmt(sample.get('cpu_percent'), '%')}[/{cpu_color}]"
    gpu_str = f"[{gpu_color}]{fmt(sample.get('gpu_percent'), '%')}[/{gpu_color}]"
    ram_str = f"[{ram_color}]{fmt(sample.get('ram_percent'), '%')}[/{ram_color}]"

    table.add_row("CPU Usage", cpu_str, "GPU Usage", gpu_str)
    table.add_row("CPU Freq", fmt(sample.get("cpu_freq_mhz"), "MHz", 0), "GPU Temp", fmt(sample.get("gpu_temp"), "°C", 0))
    table.add_row("CPU Temp", fmt(sample.get("cpu_temp"), "°C", 0), "VRAM Used", fmt(sample.get("gpu_memory_used_mb"), "MB", 0))
    table.add_row("RAM Usage", ram_str, "RAM Used", fmt(sample.get("ram_used_gb"), "GB"))
    table.add_row("Disk Read", fmt(sample.get("disk_read_mbps"), "MB/s"), "Disk Write", fmt(sample.get("disk_write_mbps"), "MB/s"))
    table.add_row("Net Down", fmt(sample.get("net_recv_mbps"), "MB/s", 3), "Net Up", fmt(sample.get("net_sent_mbps"), "MB/s", 3))

    progress_pct = min(100, int(elapsed_s / total_s * 100)) if total_s > 0 else 0
    bar_filled = int(progress_pct / 5)
    progress_bar = "[" + "#" * bar_filled + "-" * (20 - bar_filled) + f"] {progress_pct}% ({int(elapsed_s)}s/{int(total_s)}s)"

    top_cpu = sample.get("top_cpu_procs", [])
    top_proc_str = " | ".join([f"{p['name']}:{p['cpu_percent']:.0f}%" for p in top_cpu[:3] if p['cpu_percent'] > 0.5])

    panel = Panel(
        table,
        title=f"[bold yellow]FPS Doctor - Live Monitor[/bold yellow]  {progress_bar}",
        subtitle=f"[dim]Top CPU: {top_proc_str or 'idle'}[/dim]",
        border_style="blue",
    )
    return panel


def _compute_stats(samples, key):
    """Compute statistics for a metric across all samples."""
    vals = [s[key] for s in samples if s.get(key) is not None]
    if not vals:
        return {"mean": None, "min": None, "max": None, "p1": None, "p5": None, "p99": None}
    sorted_vals = sorted(vals)
    n = len(sorted_vals)

    def percentile(p):
        idx = max(0, int(n * p / 100) - 1)
        return sorted_vals[idx]

    return {
        "mean": round(statistics.mean(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "p1": round(percentile(1), 2),
        "p5": round(percentile(5), 2),
        "p99": round(percentile(99), 2),
    }


def run_monitoring(duration_seconds=600, sample_interval=1, console=None):
    """
    Monitor system performance for duration_seconds, sampling every sample_interval seconds.
    Shows live rich stats panel. Returns dict with samples, stats, spikes, throttle_events.
    """
    if console is None and RICH_OK:
        console = Console()

    samples = []
    spikes = []
    throttle_events = []

    if PSUTIL_OK:
        # Prime cpu_percent
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)

    prev_disk_io = None
    prev_net_io = None
    prev_time = None

    try:
        prev_disk_io = psutil.disk_io_counters() if PSUTIL_OK else None
        prev_net_io = psutil.net_io_counters() if PSUTIL_OK else None
        prev_time = time.time()
    except Exception:
        pass

    start_time = time.time()
    last_sample_time = start_time

    if RICH_OK and console:
        console.print(f"[cyan]Starting live monitor for {duration_seconds}s. Press Ctrl+C to stop early.[/cyan]")

    # Use Live display
    if RICH_OK:
        initial_sample = {
            "cpu_percent": None, "gpu_percent": None, "ram_percent": None,
            "cpu_freq_mhz": None, "cpu_temp": None, "gpu_temp": None,
            "gpu_memory_used_mb": None, "ram_used_gb": None,
            "disk_read_mbps": None, "disk_write_mbps": None,
            "net_sent_mbps": None, "net_recv_mbps": None,
            "top_cpu_procs": [], "top_ram_procs": [],
        }
        live_display = Live(
            _build_live_panel(initial_sample, 0, duration_seconds),
            refresh_per_second=2,
            console=console
        )
    else:
        live_display = None

    try:
        if live_display:
            live_display.start()

        while True:
            now = time.time()
            elapsed = now - start_time

            if elapsed >= duration_seconds:
                break

            # Wait for sample interval
            since_last = now - last_sample_time
            if since_last < sample_interval:
                time.sleep(min(0.5, sample_interval - since_last))
                continue

            sample, prev_disk_io, prev_net_io, prev_time = _collect_sample(
                prev_disk_io, prev_net_io, prev_time
            )
            samples.append(sample)
            last_sample_time = time.time()

            # Update live display
            if live_display:
                live_display.update(_build_live_panel(sample, elapsed, duration_seconds))

            # Spike detection
            cpu_pct = sample.get("cpu_percent")
            gpu_pct = sample.get("gpu_percent")
            ram_pct = sample.get("ram_percent")

            if (cpu_pct and cpu_pct > 95) or (gpu_pct and gpu_pct > 95) or (ram_pct and ram_pct > 90):
                spikes.append({
                    "timestamp": sample["timestamp"],
                    "cpu_percent": cpu_pct,
                    "gpu_percent": gpu_pct,
                    "ram_percent": ram_pct,
                })

            # Thermal throttle detection: CPU freq drops >10% while CPU% stays high
            if len(samples) >= 3:
                prev_s = samples[-2]
                curr_s = sample
                prev_freq = prev_s.get("cpu_freq_mhz")
                curr_freq = curr_s.get("cpu_freq_mhz")
                curr_cpu = curr_s.get("cpu_percent")
                if prev_freq and curr_freq and curr_cpu:
                    freq_drop_pct = (prev_freq - curr_freq) / prev_freq * 100
                    if freq_drop_pct > 10 and curr_cpu > 80:
                        throttle_events.append({
                            "timestamp": sample["timestamp"],
                            "prev_freq_mhz": prev_freq,
                            "curr_freq_mhz": curr_freq,
                            "drop_pct": round(freq_drop_pct, 1),
                            "cpu_percent": curr_cpu,
                        })

    except KeyboardInterrupt:
        if RICH_OK and console:
            console.print("\n[yellow]Monitoring interrupted by user.[/yellow]")
    finally:
        if live_display:
            try:
                live_display.stop()
            except Exception:
                pass

    # Compute statistics
    metric_keys = [
        "cpu_percent", "gpu_percent", "ram_percent", "cpu_freq_mhz",
        "cpu_temp", "gpu_temp", "gpu_memory_used_mb", "ram_used_gb",
        "disk_read_mbps", "disk_write_mbps", "net_sent_mbps", "net_recv_mbps",
    ]

    stats = {}
    for key in metric_keys:
        stats[key] = _compute_stats(samples, key)

    return {
        "samples": samples,
        "stats": stats,
        "spikes": spikes,
        "throttle_events": throttle_events,
        "duration_seconds": duration_seconds,
        "sample_count": len(samples),
    }
