"""Phase 6: Generate the final text report."""

import datetime
import os
import socket


TOOL_NAME = "FPS Doctor"
VERSION = "1.0.0"


def _line(char="=", width=80):
    return char * width


def _center(text, width=80):
    return text.center(width)


def _truncate(text, max_len=50):
    text = str(text)
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def _section(title):
    lines = []
    lines.append("")
    lines.append(_line("="))
    lines.append(f"  {title}")
    lines.append(_line("="))
    return "\n".join(lines)


def _subsection(title):
    return f"\n  {title}\n  " + _line("-", 76)


def _status_label(status):
    labels = {"ok": "OK      ", "warning": "WARNING ", "critical": "CRITICAL"}
    return labels.get(status, "UNKNOWN ")


def _verdict_label(verdict):
    labels = {"optimal": "OPTIMAL    ", "suboptimal": "SUBOPTIMAL ", "problematic": "PROBLEMATIC"}
    return labels.get(verdict, "UNKNOWN    ")


def _severity_label(severity):
    labels = {"low": "LOW   ", "medium": "MEDIUM", "high": "HIGH  "}
    return labels.get(severity, "UNKNOWN")


def format_system_specs(specs):
    lines = [_section("SYSTEM SPECIFICATIONS")]

    # CPU
    lines.append(_subsection("CPU"))
    cpu = specs.get("cpu", {})
    lines.append(f"  {'Name:':<22} {cpu.get('name', 'N/A')}")
    lines.append(f"  {'Cores/Threads:':<22} {cpu.get('cores', 'N/A')} cores / {cpu.get('threads', 'N/A')} threads")
    lines.append(f"  {'Base Clock:':<22} {cpu.get('base_clock_mhz', 'N/A')} MHz")
    lines.append(f"  {'Boost Clock:':<22} {cpu.get('boost_clock_mhz', 'N/A')} MHz")
    lines.append(f"  {'Architecture:':<22} {cpu.get('architecture', 'N/A')}")
    lines.append(f"  {'L2 Cache:':<22} {cpu.get('l2_cache_kb', 'N/A')} KB")
    lines.append(f"  {'L3 Cache:':<22} {cpu.get('l3_cache_kb', 'N/A')} KB")
    lines.append(f"  {'Socket:':<22} {cpu.get('socket', 'N/A')}")
    lines.append(f"  {'Stepping:':<22} {cpu.get('stepping', 'N/A')}")

    # GPU
    lines.append(_subsection("GPU"))
    gpus = specs.get("gpu", [{}])
    for i, gpu in enumerate(gpus):
        if len(gpus) > 1:
            lines.append(f"  --- GPU {i+1} ---")
        lines.append(f"  {'Name:':<22} {gpu.get('name', 'N/A')}")
        lines.append(f"  {'VRAM:':<22} {gpu.get('vram_mb', 'N/A')} MB")
        lines.append(f"  {'Driver Version:':<22} {gpu.get('driver_version', 'N/A')}")
        lines.append(f"  {'Driver Date:':<22} {gpu.get('driver_date', 'N/A')}")
        lines.append(f"  {'Resolution:':<22} {gpu.get('current_resolution', 'N/A')}")

    # RAM
    lines.append(_subsection("RAM"))
    ram = specs.get("ram", {})
    lines.append(f"  {'Total:':<22} {ram.get('total_gb', 'N/A')} GB")
    lines.append(f"  {'Speed:':<22} {ram.get('speed_mhz', 'N/A')} MHz")
    lines.append(f"  {'Type:':<22} {ram.get('type', 'N/A')}")
    lines.append(f"  {'Channels:':<22} {ram.get('channels', 'N/A')}")
    lines.append(f"  {'Slots Used:':<22} {ram.get('slots_used', 'N/A')} / {ram.get('total_slots', 'N/A')}")

    # Storage
    lines.append(_subsection("Storage"))
    col_w = [20, 8, 10, 10, 16]
    header = f"  {'Model':<{col_w[0]}} {'Type':<{col_w[1]}} {'Size(GB)':<{col_w[2]}} {'Free(GB)':<{col_w[3]}} {'Health':<{col_w[4]}}"
    lines.append(header)
    lines.append("  " + _line("-", 76))
    for drive in specs.get("storage", []):
        model = _truncate(drive.get("model", "N/A"), col_w[0])
        lines.append(
            f"  {model:<{col_w[0]}} "
            f"{str(drive.get('type', 'N/A')):<{col_w[1]}} "
            f"{str(drive.get('size_gb', 'N/A')):<{col_w[2]}} "
            f"{str(drive.get('free_gb', 'N/A')):<{col_w[3]}} "
            f"{str(drive.get('health_status', 'N/A')):<{col_w[4]}}"
        )

    # Motherboard
    lines.append(_subsection("Motherboard"))
    mb = specs.get("motherboard", {})
    lines.append(f"  {'Manufacturer:':<22} {mb.get('manufacturer', 'N/A')}")
    lines.append(f"  {'Model:':<22} {mb.get('model', 'N/A')}")
    lines.append(f"  {'BIOS Version:':<22} {mb.get('bios_version', 'N/A')}")
    lines.append(f"  {'BIOS Date:':<22} {mb.get('bios_date', 'N/A')}")

    # OS
    lines.append(_subsection("Operating System"))
    os_info = specs.get("os", {})
    lines.append(f"  {'Edition:':<22} {os_info.get('edition', 'N/A')}")
    lines.append(f"  {'Build:':<22} {os_info.get('build_number', 'N/A')}")
    lines.append(f"  {'Install Date:':<22} {os_info.get('install_date', 'N/A')}")
    lines.append(f"  {'Uptime:':<22} {os_info.get('uptime_hours', 'N/A')} hours")

    # Display
    lines.append(_subsection("Display"))
    for mon in specs.get("display", []):
        lines.append(f"  {'Monitor:':<22} {mon.get('name', 'N/A')}")
        lines.append(f"  {'Resolution:':<22} {mon.get('resolution', 'N/A')}")
        lines.append(f"  {'Refresh Rate:':<22} {mon.get('refresh_rate', 'N/A')}")

    # Network
    lines.append(_subsection("Network Adapters"))
    for adapter in specs.get("network", []):
        lines.append(f"  {'Name:':<22} {adapter.get('name', 'N/A')}")
        lines.append(f"  {'Speed:':<22} {adapter.get('speed_mbps', 'N/A')} Mbps")

    # Power
    lines.append(_subsection("Power"))
    power = specs.get("power", {})
    lines.append(f"  {'Power Plan:':<22} {power.get('power_plan_name', 'N/A')}")
    lines.append(f"  {'Plan GUID:':<22} {power.get('power_plan_guid', 'N/A')}")
    lines.append(f"  {'Is Laptop:':<22} {power.get('is_laptop', 'N/A')}")

    return "\n".join(lines)


def format_diagnosis(diagnosis):
    lines = [_section("FPS LOSS DIAGNOSIS")]

    col_check = 32
    col_status = 10
    col_value = 28
    col_rec = 42

    header = (
        f"  {'CHECK':<{col_check}} "
        f"{'STATUS':<{col_status}} "
        f"{'VALUE':<{col_value}} "
        f"{'RECOMMENDATION':<{col_rec}}"
    )

    section_labels = {
        "driver_issues": "2.1  Driver Issues",
        "background_processes": "2.2  Background Processes",
        "thermal_power": "2.3  Thermal & Power",
        "memory_issues": "2.4  Memory Issues",
        "storage_issues": "2.5  Storage Issues",
        "network_issues": "2.6  Network Issues",
        "software_overlays": "2.7  Software & Overlays",
        "windows_settings": "2.8  Windows Settings",
        "gpu_settings": "2.9  GPU Settings",
        "directx_runtimes": "2.10 DirectX & Runtimes",
        "bios_firmware": "2.11 BIOS & Firmware",
        "display_issues": "2.12 Display Issues",
    }

    for section_key, section_data in diagnosis.items():
        label = section_labels.get(section_key, section_key.replace("_", " ").title())
        lines.append(_subsection(label))
        lines.append(header)
        lines.append("  " + _line("-", 120))

        if not isinstance(section_data, dict):
            continue

        for check_name, check_data in section_data.items():
            if not isinstance(check_data, dict):
                continue
            status = check_data.get("status", "unknown")
            value = _truncate(str(check_data.get("value", "N/A")), col_value - 2)
            rec = _truncate(str(check_data.get("recommendation", "")), col_rec - 2)
            check_label = check_name.replace("_", " ").title()
            check_label = _truncate(check_label, col_check - 2)

            lines.append(
                f"  {check_label:<{col_check}} "
                f"{_status_label(status):<{col_status}} "
                f"{value:<{col_value}} "
                f"{rec:<{col_rec}}"
            )

    return "\n".join(lines)


def format_bottlenecks(bottlenecks):
    lines = [_section("BOTTLENECK ANALYSIS")]

    if not bottlenecks:
        lines.append("\n  No significant bottlenecks detected during the analysis period.")
        return "\n".join(lines)

    for i, b in enumerate(bottlenecks, 1):
        severity = b.get("severity", "unknown")
        btype = b.get("type", "Unknown")
        desc = b.get("description", "")
        rec = b.get("recommendation", "")

        lines.append(f"\n  [{i}] {btype}  [Severity: {_severity_label(severity).strip()}]")
        lines.append(f"      " + _line("-", 70))
        lines.append(f"      Description: {desc}")

        # Word wrap recommendation
        rec_words = rec.split()
        rec_line = "      Recommendation: "
        for word in rec_words:
            if len(rec_line) + len(word) + 1 > 80:
                lines.append(rec_line)
                rec_line = "                       " + word
            else:
                rec_line += word + " "
        if rec_line.strip():
            lines.append(rec_line)

    return "\n".join(lines)


def format_settings_audit(settings_audit):
    lines = [_section("SETTINGS AUDIT")]

    col_setting = 32
    col_current = 22
    col_verdict = 13
    col_rec = 45

    header = (
        f"  {'SETTING':<{col_setting}} "
        f"{'CURRENT VALUE':<{col_current}} "
        f"{'VERDICT':<{col_verdict}} "
        f"{'RECOMMENDATION':<{col_rec}}"
    )
    lines.append(header)
    lines.append("  " + _line("-", 120))

    last_category = None
    for item in settings_audit:
        cat = item.get("category", "")
        if cat != last_category:
            lines.append(f"\n  -- {cat} --")
            last_category = cat

        setting = _truncate(item.get("setting", ""), col_setting - 2)
        current = _truncate(item.get("current_value", ""), col_current - 2)
        verdict = _verdict_label(item.get("verdict", ""))
        rec = _truncate(item.get("recommendation", ""), col_rec - 2)

        lines.append(
            f"  {setting:<{col_setting}} "
            f"{current:<{col_current}} "
            f"{verdict:<{col_verdict}} "
            f"{rec:<{col_rec}}"
        )

    return "\n".join(lines)


def format_monitoring(monitoring_data):
    lines = [_section("PERFORMANCE MONITORING SUMMARY")]

    if not monitoring_data:
        lines.append("\n  No monitoring data available.")
        return "\n".join(lines)

    duration = monitoring_data.get("duration_seconds", 0)
    sample_count = monitoring_data.get("sample_count", 0)
    spikes = monitoring_data.get("spikes", [])
    throttle_events = monitoring_data.get("throttle_events", [])
    stats = monitoring_data.get("stats", {})

    lines.append(f"\n  Duration: {duration}s | Samples: {sample_count}")

    # Stats table
    lines.append(_subsection("Performance Statistics"))
    col_metric = 22
    col_mean = 10
    col_min = 10
    col_max = 10
    col_p1 = 10
    col_p5 = 10
    col_p99 = 10

    header = (
        f"  {'METRIC':<{col_metric}} "
        f"{'MEAN':>{col_mean}} "
        f"{'MIN':>{col_min}} "
        f"{'MAX':>{col_max}} "
        f"{'P1':>{col_p1}} "
        f"{'P5':>{col_p5}} "
        f"{'P99':>{col_p99}}"
    )
    lines.append(header)
    lines.append("  " + _line("-", 90))

    metric_display = [
        ("cpu_percent", "CPU %"),
        ("gpu_percent", "GPU %"),
        ("ram_percent", "RAM %"),
        ("cpu_freq_mhz", "CPU Freq (MHz)"),
        ("cpu_temp", "CPU Temp (C)"),
        ("gpu_temp", "GPU Temp (C)"),
        ("gpu_memory_used_mb", "VRAM Used (MB)"),
        ("ram_used_gb", "RAM Used (GB)"),
        ("disk_read_mbps", "Disk Read (MB/s)"),
        ("disk_write_mbps", "Disk Write (MB/s)"),
        ("net_recv_mbps", "Net Down (MB/s)"),
        ("net_sent_mbps", "Net Up (MB/s)"),
    ]

    for key, label in metric_display:
        s = stats.get(key, {})
        if s.get("mean") is None:
            continue

        def fmt(v):
            return f"{v:.1f}" if v is not None else "N/A"

        lines.append(
            f"  {label:<{col_metric}} "
            f"{fmt(s.get('mean')):>{col_mean}} "
            f"{fmt(s.get('min')):>{col_min}} "
            f"{fmt(s.get('max')):>{col_max}} "
            f"{fmt(s.get('p1')):>{col_p1}} "
            f"{fmt(s.get('p5')):>{col_p5}} "
            f"{fmt(s.get('p99')):>{col_p99}}"
        )

    # Spikes
    lines.append(_subsection(f"Performance Spikes ({len(spikes)} detected)"))
    if spikes:
        for spike in spikes[:20]:  # Cap at 20
            ts = spike.get("timestamp", "")[:19]
            cpu = spike.get("cpu_percent")
            gpu = spike.get("gpu_percent")
            ram = spike.get("ram_percent")
            lines.append(
                f"  {ts}  CPU:{cpu:.1f if cpu else 'N/A'}%  "
                f"GPU:{gpu:.1f if gpu else 'N/A'}%  "
                f"RAM:{ram:.1f if ram else 'N/A'}%"
            )
        if len(spikes) > 20:
            lines.append(f"  ... and {len(spikes) - 20} more spikes")
    else:
        lines.append("  No performance spikes detected.")

    # Throttle events
    lines.append(_subsection(f"Thermal Throttle Events ({len(throttle_events)} detected)"))
    if throttle_events:
        for ev in throttle_events[:10]:
            ts = ev.get("timestamp", "")[:19]
            lines.append(
                f"  {ts}  Freq: {ev.get('prev_freq_mhz')}MHz -> {ev.get('curr_freq_mhz')}MHz  "
                f"Drop: {ev.get('drop_pct')}%  CPU Load: {ev.get('cpu_percent')}%"
            )
    else:
        lines.append("  No thermal throttle events detected.")

    return "\n".join(lines)


def format_recommendations(diagnosis, bottlenecks, settings_audit):
    """Build deduplicated, priority-sorted final recommendations."""
    lines = [_section("FINAL RECOMMENDATIONS (Priority Sorted)")]

    recs = []

    # From diagnosis (critical and warning items)
    for section_key, section_data in diagnosis.items():
        if not isinstance(section_data, dict):
            continue
        for check_name, check_data in section_data.items():
            if not isinstance(check_data, dict):
                continue
            status = check_data.get("status", "ok")
            rec = check_data.get("recommendation", "")
            if status == "critical" and rec:
                recs.append({"priority": 1, "label": "CRITICAL", "source": check_name, "text": rec})
            elif status == "warning" and rec:
                recs.append({"priority": 2, "label": "HIGH    ", "source": check_name, "text": rec})

    # From bottlenecks
    severity_to_priority = {"high": 1, "medium": 2, "low": 3}
    for b in bottlenecks:
        sev = b.get("severity", "low")
        rec = b.get("recommendation", "")
        if rec:
            recs.append({
                "priority": severity_to_priority.get(sev, 3),
                "label": {"high": "CRITICAL", "medium": "HIGH    ", "low": "MEDIUM  "}.get(sev, "MEDIUM  "),
                "source": b.get("type", ""),
                "text": rec,
            })

    # From settings audit (problematic and suboptimal)
    for item in settings_audit:
        verdict = item.get("verdict", "optimal")
        rec = item.get("recommendation", "")
        if verdict == "problematic" and rec:
            recs.append({"priority": 2, "label": "HIGH    ", "source": item.get("setting", ""), "text": rec})
        elif verdict == "suboptimal" and rec:
            recs.append({"priority": 3, "label": "MEDIUM  ", "source": item.get("setting", ""), "text": rec})

    # Deduplicate by text similarity (simple: exact match)
    seen_texts = set()
    unique_recs = []
    for r in recs:
        key = r["text"][:80]
        if key not in seen_texts:
            seen_texts.add(key)
            unique_recs.append(r)

    unique_recs.sort(key=lambda x: x["priority"])

    if not unique_recs:
        lines.append("\n  No recommendations — system appears well optimized!")
        return "\n".join(lines)

    for i, r in enumerate(unique_recs, 1):
        lines.append(f"\n  [{i:2d}] [{r['label']}] {r['source']}")
        # Word wrap the recommendation text at 76 chars
        words = r["text"].split()
        current_line = "       "
        for word in words:
            if len(current_line) + len(word) + 1 > 79:
                lines.append(current_line)
                current_line = "       " + word
            else:
                current_line += word + " "
        if current_line.strip():
            lines.append(current_line)

    return "\n".join(lines)


def generate_report(system_specs, diagnosis, bottlenecks, settings_audit, monitoring_data, output_path):
    """Write comprehensive report to output_path."""
    lines = []

    # Header
    lines.append(_line("="))
    lines.append(_center(f"{TOOL_NAME}  v{VERSION}", 80))
    lines.append(_center("Windows PC Performance Diagnostic Report", 80))
    lines.append(_line("="))
    lines.append(f"  Generated:  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Machine:    {system_specs.get('hostname', socket.gethostname())}")
    lines.append(f"  OS:         {system_specs.get('os', {}).get('edition', 'N/A')}")
    lines.append(_line("="))

    lines.append(format_system_specs(system_specs))
    lines.append(format_diagnosis(diagnosis))
    lines.append(format_bottlenecks(bottlenecks))
    lines.append(format_settings_audit(settings_audit))
    lines.append(format_monitoring(monitoring_data))
    lines.append(format_recommendations(diagnosis, bottlenecks, settings_audit))

    lines.append("\n")
    lines.append(_line("="))
    lines.append(_center(f"End of {TOOL_NAME} Report", 80))
    lines.append(_line("="))

    report_text = "\n".join(lines)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
    except Exception as e:
        # Try fallback path
        fallback = os.path.join(os.path.expanduser("~"), "fps_doctor_report.txt")
        with open(fallback, "w", encoding="utf-8") as f:
            f.write(report_text)
        return fallback

    return output_path
