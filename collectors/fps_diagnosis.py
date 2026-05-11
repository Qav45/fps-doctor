"""Phase 2: Exhaustive FPS loss checks."""

import subprocess
import socket
import time
import os
import winreg
import datetime

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

from utils.wmi_helpers import get_wmi_client, wmi_query
from utils.registry import read_reg, read_reg_dword, reg_key_exists, list_reg_subkeys, list_reg_values
from utils.known_issues import FPS_KILLER_PROCESSES, PROBLEMATIC_SERVICES


def _run(cmd, default=""):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip()
    except Exception:
        return default


def _ok(value, recommendation=""):
    return {"status": "ok", "value": value, "recommendation": recommendation}


def _warn(value, recommendation=""):
    return {"status": "warning", "value": value, "recommendation": recommendation}


def _crit(value, recommendation=""):
    return {"status": "critical", "value": value, "recommendation": recommendation}


# ─── 2.1 Driver Issues ──────────────────────────────────────────────────────

def check_driver_issues(wmi_client):
    results = {}

    # GPU driver age
    try:
        rows = wmi_query(
            wmi_client,
            "SELECT DriverDate, Name FROM Win32_VideoController",
            ["DriverDate", "Name"]
        )
        if rows:
            dd = rows[0].get("DriverDate") or ""
            if len(dd) >= 8:
                driver_dt = datetime.datetime(int(dd[0:4]), int(dd[4:6]), int(dd[6:8]))
                age_days = (datetime.datetime.now() - driver_dt).days
                if age_days > 365:
                    results["gpu_driver_age_days"] = _warn(
                        age_days,
                        "GPU driver is over a year old. Update via manufacturer website or GeForce Experience/AMD Software."
                    )
                elif age_days > 180:
                    results["gpu_driver_age_days"] = _warn(
                        age_days,
                        "GPU driver is 6+ months old. Consider updating for performance improvements and bug fixes."
                    )
                else:
                    results["gpu_driver_age_days"] = _ok(age_days)
            else:
                results["gpu_driver_age_days"] = _warn("N/A", "Could not determine GPU driver date.")
        else:
            results["gpu_driver_age_days"] = _warn("N/A", "No GPU detected via WMI.")
    except Exception:
        results["gpu_driver_age_days"] = _warn("Error", "Could not query GPU driver date.")

    # Chipset driver version
    try:
        chipset_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e97d-e325-11ce-bfc1-08002be10318}"
        subkeys = list_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, chipset_path)
        chipset_ver = "N/A"
        for sk in subkeys:
            if sk.startswith("0"):
                ver = read_reg(
                    winreg.HKEY_LOCAL_MACHINE,
                    f"{chipset_path}\\{sk}",
                    "DriverVersion"
                )
                if ver:
                    chipset_ver = ver
                    break
        results["chipset_driver_version"] = _ok(chipset_ver) if chipset_ver != "N/A" else _warn(
            "N/A", "Could not read chipset driver version from registry."
        )
    except Exception:
        results["chipset_driver_version"] = _warn("Error", "Registry read failed for chipset driver.")

    # Device manager errors
    try:
        error_rows = wmi_query(
            wmi_client,
            "SELECT Name, ConfigManagerErrorCode FROM Win32_PnPEntity WHERE ConfigManagerErrorCode != 0",
            ["Name", "ConfigManagerErrorCode"]
        )
        error_count = len(error_rows)
        error_names = [r.get("Name") or "Unknown" for r in error_rows[:5]]
        if error_count > 0:
            results["device_manager_errors"] = _crit(
                f"{error_count} device(s) with errors: {', '.join(error_names)}",
                "Open Device Manager and resolve all devices showing errors (yellow ! icons)."
            )
        else:
            results["device_manager_errors"] = _ok("No errors", "All devices functioning correctly.")
    except Exception:
        results["device_manager_errors"] = _warn("Error", "Could not query device errors via WMI.")

    # Generic Microsoft drivers
    try:
        generic_rows = wmi_query(
            wmi_client,
            "SELECT Name, DriverProviderName FROM Win32_PnPSignedDriver WHERE DriverProviderName = 'Microsoft'",
            ["Name", "DriverProviderName"]
        )
        generic_count = len(generic_rows)
        # Filter out known-OK Microsoft drivers
        problematic = [r.get("Name") or "" for r in generic_rows
                       if any(k in (r.get("Name") or "") for k in ["Display", "Video", "USB", "Network", "Audio"])]
        if len(problematic) > 0:
            results["generic_microsoft_drivers"] = _warn(
                f"{len(problematic)} device(s) using generic Microsoft drivers",
                f"Install manufacturer drivers for: {', '.join(problematic[:3])}. Generic drivers may lack performance optimizations."
            )
        else:
            results["generic_microsoft_drivers"] = _ok(
                f"{generic_count} devices on Microsoft drivers (system components)",
                "No critical devices using generic drivers."
            )
    except Exception:
        results["generic_microsoft_drivers"] = _warn("Error", "Could not query driver providers.")

    return results


# ─── 2.2 Background Processes ───────────────────────────────────────────────

def check_background_processes():
    results = {}

    if not PSUTIL_OK:
        return {"error": _warn("psutil unavailable", "Install psutil for process analysis.")}

    try:
        all_procs = []
        fps_killers_found = []
        total_bg_cpu = 0.0

        for proc in psutil.process_iter(["name", "pid", "cpu_percent", "memory_info", "status"]):
            try:
                pinfo = proc.info
                pname = pinfo.get("name") or ""
                cpu = pinfo.get("cpu_percent") or 0.0
                mem_mb = (pinfo.get("memory_info").rss // (1024 * 1024)) if pinfo.get("memory_info") else 0
                all_procs.append({"name": pname, "pid": pinfo.get("pid"), "cpu": cpu, "mem_mb": mem_mb})

                pname_lower = pname.lower()
                for killer, desc in FPS_KILLER_PROCESSES.items():
                    if killer.lower() == pname_lower:
                        fps_killers_found.append({"name": pname, "reason": desc, "cpu": cpu, "mem_mb": mem_mb})
                        total_bg_cpu += cpu
                        break
            except Exception:
                continue

        total_procs = len(all_procs)
        if total_procs > 200:
            results["total_process_count"] = _crit(
                total_procs,
                "Over 200 processes running. This is abnormally high. Review startup programs and services."
            )
        elif total_procs > 150:
            results["total_process_count"] = _warn(
                total_procs,
                "High process count. Disable unnecessary startup programs via Task Manager > Startup."
            )
        else:
            results["total_process_count"] = _ok(total_procs)

        if fps_killers_found:
            killer_names = [f["name"] for f in fps_killers_found]
            results["fps_killer_processes"] = _warn(
                f"Found: {', '.join(killer_names)}",
                "Close or disable these processes while gaming: " + "; ".join(
                    [f"{f['name']} - {f['reason'][:60]}" for f in fps_killers_found[:3]]
                )
            )
        else:
            results["fps_killer_processes"] = _ok("None detected", "No known FPS-killing processes running.")

        # Windows Update check
        update_procs = [p for p in all_procs if p["name"].lower() in ("tiworker.exe", "waasmedic.exe", "wuauclt.exe")]
        if update_procs:
            results["windows_update_running"] = _warn(
                "Windows Update is actively running",
                "Windows Update is running in background. Performance may be degraded. Let it finish or pause updates."
            )
        else:
            results["windows_update_running"] = _ok("Not actively running")

        # Search Indexer CPU
        indexer = next((p for p in all_procs if p["name"].lower() == "searchindexer.exe"), None)
        if indexer and indexer["cpu"] > 10:
            results["search_indexer_cpu"] = _warn(
                f"{indexer['cpu']:.1f}% CPU",
                "Search Indexer is using high CPU. Consider pausing indexing or excluding game folders."
            )
        else:
            results["search_indexer_cpu"] = _ok(
                f"{indexer['cpu']:.1f}% CPU" if indexer else "Not running"
            )

        # Defender CPU
        defender = next((p for p in all_procs if p["name"].lower() == "msmpeng.exe"), None)
        if defender and defender["cpu"] > 15:
            results["windows_defender_cpu"] = _warn(
                f"{defender['cpu']:.1f}% CPU",
                "Windows Defender is using high CPU. Add game folders to exclusions in Windows Security settings."
            )
        elif defender:
            results["windows_defender_cpu"] = _ok(f"{defender['cpu']:.1f}% CPU")
        else:
            results["windows_defender_cpu"] = _ok("Not detected or not running")

        # Third-party AV
        av_processes = ["avp.exe", "avgnt.exe", "avguard.exe", "bdagent.exe", "mcshield.exe",
                        "mbam.exe", "malwarebytes.exe", "norton.exe", "nortonsecurity.exe",
                        "csc.exe", "savservice.exe", "esets_daemon.exe"]
        found_av = [p["name"] for p in all_procs if p["name"].lower() in av_processes]
        if found_av:
            results["third_party_antivirus"] = _warn(
                f"Found: {', '.join(found_av)}",
                "Third-party AV can cause significant performance overhead. Add game executables to exclusions."
            )
        else:
            results["third_party_antivirus"] = _ok("None detected")

    except Exception as e:
        results["process_check_error"] = _warn(f"Error: {e}", "Could not complete process analysis.")

    # SysMain service check
    try:
        import winreg
        sysmain_start = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\SysMain",
            "Start",
            default=None
        )
        if sysmain_start == 4:
            results["sysmain_service"] = _ok("Disabled")
        elif sysmain_start in (2, 3):
            results["sysmain_service"] = _warn(
                "Enabled",
                "SysMain (Superfetch) can cause HDD thrashing on mechanical drives. Safe to disable on SSD-only systems."
            )
        else:
            results["sysmain_service"] = _ok(f"Status: {sysmain_start}")
    except Exception:
        results["sysmain_service"] = _warn("Unknown", "Could not check SysMain service status.")

    return results


# ─── 2.3 Thermal & Power ────────────────────────────────────────────────────

def check_thermal_power():
    results = {}

    # CPU/GPU temps via psutil
    if PSUTIL_OK:
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for chip, entries in temps.items():
                    for entry in entries:
                        if "cpu" in chip.lower() or "core" in (entry.label or "").lower():
                            temp = entry.current
                            if temp > 95:
                                results["cpu_temp"] = _crit(
                                    f"{temp}°C",
                                    "CPU is critically hot. Check thermal paste, cooler mounting, and case airflow immediately."
                                )
                            elif temp > 85:
                                results["cpu_temp"] = _warn(
                                    f"{temp}°C",
                                    "CPU running hot. Clean dust from cooler, check thermal paste age (replace if >3 years)."
                                )
                            else:
                                results["cpu_temp"] = _ok(f"{temp}°C")
                            break
                    if "cpu_temp" in results:
                        break
            if "cpu_temp" not in results:
                results["cpu_temp"] = _warn(
                    "N/A",
                    "Could not read CPU temperature. Install HWiNFO or OpenHardwareMonitor for temperature monitoring."
                )
        except Exception:
            results["cpu_temp"] = _warn("N/A", "Temperature sensors unavailable on this system.")
    else:
        results["cpu_temp"] = _warn("N/A", "psutil not available for temperature reading.")

    # Power plan
    output = _run(["powercfg", "/getactivescheme"], "")
    power_plan_name = "Unknown"
    power_plan_guid = ""
    if output:
        parts = output.split()
        for part in parts:
            if "-" in part and len(part) == 36:
                power_plan_guid = part
        if "(" in output and ")" in output:
            power_plan_name = output[output.index("(") + 1:output.rindex(")")]

    HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    ULTIMATE_GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"
    BALANCED_GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"
    POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"

    if power_plan_guid.lower() in (HIGH_PERF_GUID, ULTIMATE_GUID):
        results["power_plan"] = _ok(power_plan_name)
    elif power_plan_guid.lower() == BALANCED_GUID:
        results["power_plan"] = _warn(
            power_plan_name,
            "Switch to High Performance or Ultimate Performance power plan for consistent CPU/GPU boost clocks."
        )
    elif power_plan_guid.lower() == POWER_SAVER_GUID:
        results["power_plan"] = _crit(
            power_plan_name,
            "Power Saver plan severely limits CPU frequency. Switch to High Performance immediately."
        )
    else:
        results["power_plan"] = _warn(
            power_plan_name or "Custom",
            "Using custom/unknown power plan. Ensure processor max state is 100% and GPU power is maximum performance."
        )

    # CPU parking
    try:
        parking_path = r"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b647-c1df-4637-891a-dec35c318583"
        parking_val = read_reg(winreg.HKEY_LOCAL_MACHINE, parking_path, "ValueMax", default=None)
        if parking_val is not None and int(parking_val) > 0:
            results["cpu_core_parking"] = _warn(
                f"Enabled (ValueMax={parking_val})",
                "CPU core parking may reduce responsiveness. Disable via powercfg or ParkControl utility."
            )
        else:
            results["cpu_core_parking"] = _ok("Disabled or minimal")
    except Exception:
        results["cpu_core_parking"] = _ok("Could not determine")

    # USB selective suspend
    try:
        usb_suspend = _run(["powercfg", "/query", "SCHEME_CURRENT", "2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"], "")
        if "0x00000000" in usb_suspend:
            results["usb_selective_suspend"] = _ok("Disabled")
        elif "0x00000001" in usb_suspend:
            results["usb_selective_suspend"] = _warn(
                "Enabled",
                "USB selective suspend can cause input device stutters. Disable in Power Options > USB Settings."
            )
        else:
            results["usb_selective_suspend"] = _ok("Unknown/Default")
    except Exception:
        results["usb_selective_suspend"] = _ok("Could not determine")

    # Processor max state
    try:
        max_state_out = _run(["powercfg", "/query", "SCHEME_CURRENT", "54533251-82be-4824-96c1-47b60b740d00", "bc5038f7-23e0-4960-96da-33abaf5935ec"], "")
        if "0x00000064" in max_state_out:
            results["processor_max_state"] = _ok("100%")
        elif max_state_out:
            results["processor_max_state"] = _warn(
                "Below 100%",
                "Processor max state is below 100%. Set to 100% in Power Options > Processor Power Management."
            )
        else:
            results["processor_max_state"] = _ok("Could not determine")
    except Exception:
        results["processor_max_state"] = _ok("Could not determine")

    return results


# ─── 2.4 Memory Issues ──────────────────────────────────────────────────────

def check_memory_issues():
    results = {}

    if not PSUTIL_OK:
        return {"error": _warn("psutil unavailable", "Install psutil.")}

    try:
        vm = psutil.virtual_memory()
        ram_pct = vm.percent
        if ram_pct > 90:
            results["ram_usage"] = _crit(
                f"{ram_pct:.1f}%",
                "RAM usage critically high. Close background applications or upgrade RAM."
            )
        elif ram_pct > 75:
            results["ram_usage"] = _warn(
                f"{ram_pct:.1f}%",
                "RAM usage elevated. Close unused applications to free memory for games."
            )
        else:
            results["ram_usage"] = _ok(f"{ram_pct:.1f}%")
    except Exception:
        results["ram_usage"] = _warn("N/A", "Could not read RAM usage.")

    try:
        swap = psutil.swap_memory()
        if swap.total > 0:
            swap_pct = swap.percent
            if swap_pct > 50:
                results["pagefile_usage"] = _warn(
                    f"{swap_pct:.1f}% ({swap.used // (1024**3):.1f}GB used)",
                    "High pagefile usage means Windows is using disk as RAM, causing stutters. Add more RAM."
                )
            else:
                results["pagefile_usage"] = _ok(f"{swap_pct:.1f}%")
        else:
            results["pagefile_usage"] = _warn("No pagefile", "No pagefile configured. This may cause crashes in low-memory situations.")
    except Exception:
        results["pagefile_usage"] = _warn("N/A", "Could not read pagefile usage.")

    # Hardware reserved memory check
    try:
        import winreg
        wmi_client = get_wmi_client()
        os_rows = wmi_query(
            wmi_client,
            "SELECT TotalPhysicalMemory, TotalVirtualMemorySize FROM Win32_OperatingSystem",
            ["TotalPhysicalMemory", "TotalVirtualMemorySize"]
        )
        if os_rows and PSUTIL_OK:
            reported_kb = int(os_rows[0].get("TotalPhysicalMemory") or 0)
            actual = psutil.virtual_memory().total
            diff_gb = (actual - reported_kb * 1024) / (1024 ** 3) if reported_kb > 0 else 0
            if diff_gb > 0.5:
                results["hardware_reserved_memory"] = _warn(
                    f"~{diff_gb:.1f}GB reserved",
                    "Significant memory reserved by hardware. Check BIOS settings for iGPU VRAM allocation."
                )
            else:
                results["hardware_reserved_memory"] = _ok("Normal")
    except Exception:
        results["hardware_reserved_memory"] = _ok("Could not determine")

    return results


# ─── 2.5 Storage Issues ─────────────────────────────────────────────────────

def check_storage_issues():
    results = {}

    if PSUTIL_OK:
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    pct_free = (usage.free / usage.total) * 100
                    drive_letter = part.mountpoint.rstrip("\\")
                    key = f"free_space_{drive_letter}"
                    if pct_free < 5:
                        results[key] = _crit(
                            f"{pct_free:.1f}% free ({usage.free // (1024**3):.0f}GB)",
                            f"Drive {drive_letter} is critically full. Free at least 15% for optimal performance."
                        )
                    elif pct_free < 15:
                        results[key] = _warn(
                            f"{pct_free:.1f}% free ({usage.free // (1024**3):.0f}GB)",
                            f"Drive {drive_letter} has low free space. Windows needs 15%+ for proper operation."
                        )
                    else:
                        results[key] = _ok(f"{pct_free:.1f}% free")
                except Exception:
                    pass
        except Exception:
            results["disk_space_error"] = _warn("Error", "Could not check disk space.")

    # SSD TRIM status
    try:
        trim_output = _run(["fsutil", "behavior", "query", "DisableDeleteNotify"], "")
        if "0" in trim_output:
            results["ssd_trim"] = _ok("Enabled (TRIM active)")
        elif "1" in trim_output:
            results["ssd_trim"] = _warn(
                "Disabled",
                "SSD TRIM is disabled. Enable with: fsutil behavior set DisableDeleteNotify 0"
            )
        else:
            results["ssd_trim"] = _ok("Could not determine")
    except Exception:
        results["ssd_trim"] = _ok("Could not determine")

    # Storage controller mode
    try:
        ahci_start = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\storahci",
            "Start",
            default=None
        )
        if ahci_start == 0:
            results["storage_controller_mode"] = _ok("AHCI/NVMe (storahci active)")
        else:
            results["storage_controller_mode"] = _ok("Standard mode")
    except Exception:
        results["storage_controller_mode"] = _ok("Could not determine")

    return results


# ─── 2.6 Network Issues ─────────────────────────────────────────────────────

def check_network_issues():
    results = {}

    # Ping test
    try:
        ping_out = _run(["ping", "-n", "4", "8.8.8.8"], "")
        ping_ms = None
        for line in ping_out.split("\n"):
            if "Average" in line or "average" in line:
                parts = line.split("=")
                if parts:
                    try:
                        ping_ms = int(parts[-1].strip().replace("ms", "").strip())
                    except Exception:
                        pass
        if ping_ms is not None:
            if ping_ms > 100:
                results["ping_google"] = _warn(
                    f"{ping_ms}ms",
                    "High ping to 8.8.8.8. Check for background downloads, QoS settings, or ISP issues."
                )
            else:
                results["ping_google"] = _ok(f"{ping_ms}ms")
        elif "Request timed out" in ping_out or "could not find host" in ping_out.lower():
            results["ping_google"] = _crit("No connectivity", "Cannot reach 8.8.8.8. Check network connection.")
        else:
            results["ping_google"] = _ok("Reachable (could not parse ms)")
    except Exception:
        results["ping_google"] = _warn("N/A", "Could not run ping test.")

    # DNS response time
    try:
        start = time.time()
        socket.getaddrinfo("www.google.com", 80)
        dns_ms = round((time.time() - start) * 1000, 1)
        if dns_ms > 200:
            results["dns_response_time"] = _warn(
                f"{dns_ms}ms",
                "Slow DNS resolution. Try using 8.8.8.8 or 1.1.1.1 as DNS servers."
            )
        else:
            results["dns_response_time"] = _ok(f"{dns_ms}ms")
    except Exception:
        results["dns_response_time"] = _warn("N/A", "Could not measure DNS response time.")

    # Network throttling index
    try:
        nti = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
            "NetworkThrottlingIndex",
            default=None
        )
        if nti is None:
            results["network_throttling_index"] = _warn(
                "Default (10)",
                "Set NetworkThrottlingIndex to 0xffffffff (FFFFFFFF) to disable network throttling for gaming."
            )
        elif nti == 0xFFFFFFFF or nti == -1:
            results["network_throttling_index"] = _ok("Disabled (FFFFFFFF)")
        else:
            results["network_throttling_index"] = _warn(
                hex(nti),
                "NetworkThrottlingIndex is set. For gaming, set to 0xffffffff to disable throttling."
            )
    except Exception:
        results["network_throttling_index"] = _warn("N/A", "Could not read network throttling setting.")

    # Nagle's algorithm
    try:
        tcp_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        ifaces = list_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, tcp_path)
        nagle_disabled = False
        for iface in ifaces:
            ack = read_reg(winreg.HKEY_LOCAL_MACHINE, f"{tcp_path}\\{iface}", "TcpAckFrequency", default=None)
            nodelay = read_reg(winreg.HKEY_LOCAL_MACHINE, f"{tcp_path}\\{iface}", "TCPNoDelay", default=None)
            if ack == 1 and nodelay == 1:
                nagle_disabled = True
                break
        if nagle_disabled:
            results["nagle_algorithm"] = _ok("Disabled (TcpAckFrequency=1, TCPNoDelay=1)")
        else:
            results["nagle_algorithm"] = _warn(
                "Enabled (default)",
                "Nagle's algorithm adds latency. For gaming, disable by setting TcpAckFrequency=1 and TCPNoDelay=1 per adapter."
            )
    except Exception:
        results["nagle_algorithm"] = _ok("Could not determine")

    return results


# ─── 2.7 Software Overlays ──────────────────────────────────────────────────

def check_software_overlays():
    results = {}

    if not PSUTIL_OK:
        return {"error": _warn("psutil unavailable", "Install psutil.")}

    running_procs = {}
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name") or ""
                running_procs[name.lower()] = name
            except Exception:
                pass
    except Exception:
        pass

    # Check known overlay apps
    overlay_checks = {
        "discord": "discord.exe",
        "steam_overlay": "steamwebhelper.exe",
        "geforce_experience": "gfexperienceservice.exe",
        "xbox_game_bar": "gamebar.exe",
        "obs": "obs64.exe",
        "browser_overlays": "chrome.exe",
    }
    for label, proc_name in overlay_checks.items():
        if proc_name.lower() in running_procs:
            results[label] = _warn(
                f"Running ({running_procs[proc_name.lower()]})",
                f"Disable in-game overlay for {label.replace('_', ' ')} while gaming for better performance."
            )
        else:
            results[label] = _ok("Not running")

    # Xbox Game DVR
    try:
        dvr_val = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
            "AllowGameDVR",
            default=None
        )
        if dvr_val == 0:
            results["xbox_game_dvr"] = _ok("Disabled")
        elif dvr_val == 1:
            results["xbox_game_dvr"] = _warn(
                "Enabled",
                "Xbox Game DVR records gameplay in background. Disable in Xbox app > Settings > Captures."
            )
        else:
            results["xbox_game_dvr"] = _warn("Unknown", "Could not determine Game DVR status.")
    except Exception:
        results["xbox_game_dvr"] = _warn("N/A", "Could not read Game DVR registry setting.")

    # Cloud sync running
    cloud_procs = {
        "onedrive.exe": "OneDrive",
        "googledrivefs.exe": "Google Drive",
        "dropbox.exe": "Dropbox",
    }
    for proc_name, service_name in cloud_procs.items():
        if proc_name in running_procs:
            results[f"cloud_sync_{service_name.lower().replace(' ', '_')}"] = _warn(
                f"{service_name} running",
                f"Pause {service_name} sync while gaming to prevent disk I/O spikes."
            )

    # RGB software
    rgb_procs = {
        "icue.exe": "Corsair iCUE",
        "razersynapse.exe": "Razer Synapse",
        "lghub.exe": "Logitech G HUB",
        "aurasync.exe": "ASUS Aura Sync",
        "rgbfusion.exe": "Gigabyte RGB Fusion",
        "mysticlight.exe": "MSI Mystic Light",
    }
    rgb_found = []
    for proc_name, service_name in rgb_procs.items():
        if proc_name in running_procs:
            rgb_found.append(service_name)

    if rgb_found:
        results["rgb_software"] = _warn(
            f"Running: {', '.join(rgb_found)}",
            "RGB management software adds CPU overhead. Consider using static colors or lighter alternatives."
        )
    else:
        results["rgb_software"] = _ok("No RGB software detected")

    # VPN
    vpn_procs = ["openvpn.exe", "nordvpn.exe", "expressvpn.exe", "protonvpn.exe",
                 "mullvad-vpn.exe", "wireguard.exe", "softethervpn.exe"]
    vpn_found = [p for p in vpn_procs if p in running_procs]
    if vpn_found:
        results["vpn_software"] = _warn(
            f"Running: {', '.join(vpn_found)}",
            "VPN can add latency to online games. Disable when gaming unless required."
        )
    else:
        results["vpn_software"] = _ok("No VPN detected")

    return results


# ─── 2.8 Windows Settings ───────────────────────────────────────────────────

def check_windows_settings():
    results = {}

    # Game Mode
    try:
        game_mode = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\GameBar",
            "AllowAutoGameMode",
            default=None
        )
        if game_mode == 1:
            results["game_mode"] = _ok("Enabled")
        elif game_mode == 0:
            results["game_mode"] = _warn("Disabled", "Enable Game Mode in Settings > Gaming > Game Mode.")
        else:
            results["game_mode"] = _warn("Unknown", "Could not determine Game Mode status.")
    except Exception:
        results["game_mode"] = _warn("N/A", "Could not read Game Mode setting.")

    # HAGS (Hardware-Accelerated GPU Scheduling)
    try:
        hags = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
            "HwSchMode",
            default=None
        )
        if hags == 2:
            results["hags"] = _ok("Enabled")
        elif hags == 1:
            results["hags"] = _warn(
                "Disabled",
                "Enable Hardware-Accelerated GPU Scheduling in Settings > System > Display > Graphics > Default graphics settings."
            )
        else:
            results["hags"] = _warn("Unknown", "Could not determine HAGS status.")
    except Exception:
        results["hags"] = _warn("N/A", "Could not read HAGS registry setting.")

    # Fullscreen optimizations
    try:
        fse = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"System\GameConfigStore",
            "GameDVR_FSEBehaviorMode",
            default=None
        )
        if fse == 2:
            results["fullscreen_optimizations"] = _ok("Fullscreen Exclusive preferred")
        elif fse == 0:
            results["fullscreen_optimizations"] = _warn(
                "Enabled (may override FSE)",
                "Fullscreen optimizations may force borderless windowed mode. Disable per-game if you prefer exclusive fullscreen."
            )
        else:
            results["fullscreen_optimizations"] = _ok("Default")
    except Exception:
        results["fullscreen_optimizations"] = _ok("Default/Unknown")

    # Visual effects
    try:
        vfx = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
            "VisualFXSetting",
            default=None
        )
        vfx_map = {0: "Let Windows decide", 1: "Best appearance", 2: "Best performance", 3: "Custom"}
        if vfx == 2:
            results["visual_effects"] = _ok("Best performance")
        elif vfx == 3:
            results["visual_effects"] = _ok("Custom (verify settings)")
        elif vfx is not None:
            results["visual_effects"] = _warn(
                vfx_map.get(vfx, f"Setting={vfx}"),
                "Set Visual Effects to 'Adjust for best performance' in System Properties > Advanced > Performance."
            )
        else:
            results["visual_effects"] = _warn("Unknown", "Could not read visual effects setting.")
    except Exception:
        results["visual_effects"] = _warn("N/A", "Could not check visual effects setting.")

    # Transparency effects
    try:
        trans = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "EnableTransparency",
            default=None
        )
        if trans == 0:
            results["transparency_effects"] = _ok("Disabled")
        elif trans == 1:
            results["transparency_effects"] = _warn(
                "Enabled",
                "Disable transparency effects in Settings > Personalization > Colors for minor performance gain."
            )
        else:
            results["transparency_effects"] = _warn("Unknown", "Could not determine transparency setting.")
    except Exception:
        results["transparency_effects"] = _ok("Unknown")

    # Animations
    try:
        anim = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics",
            "MinAnimate",
            default=None
        )
        if anim == "0" or anim == 0:
            results["window_animations"] = _ok("Disabled")
        elif anim == "1" or anim == 1:
            results["window_animations"] = _warn(
                "Enabled",
                "Disable window animations in Visual Effects settings for snappier response."
            )
        else:
            results["window_animations"] = _ok("Unknown/Default")
    except Exception:
        results["window_animations"] = _ok("Unknown")

    # Memory Integrity (HVCI)
    try:
        hvci = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
            "Enabled",
            default=None
        )
        if hvci == 1:
            results["memory_integrity_hvci"] = _warn(
                "Enabled",
                "Memory Integrity (HVCI) adds ~5-15% performance overhead. Disable in Windows Security > Device Security if not required by policy."
            )
        elif hvci == 0:
            results["memory_integrity_hvci"] = _ok("Disabled")
        else:
            results["memory_integrity_hvci"] = _ok("Not configured/Unknown")
    except Exception:
        results["memory_integrity_hvci"] = _ok("Unknown")

    # Hyper-V
    try:
        hyperv_output = _run(["bcdedit", "/enum"], "")
        if "hypervisorlaunchtype" in hyperv_output.lower():
            if "auto" in hyperv_output.lower():
                results["hyper_v"] = _warn(
                    "Enabled",
                    "Hyper-V virtualization can add latency and reduce gaming performance. Disable if not needed."
                )
            else:
                results["hyper_v"] = _ok("Disabled")
        else:
            results["hyper_v"] = _ok("Not configured")
    except Exception:
        results["hyper_v"] = _ok("Could not determine")

    # Windows Insider
    try:
        insider = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\WindowsSelfHost\UI\Selection",
            "ContentType",
            default=None
        )
        if insider:
            results["windows_insider"] = _warn(
                f"Enrolled: {insider}",
                "Windows Insider builds may have bugs and instability. Consider stable release for gaming."
            )
        else:
            results["windows_insider"] = _ok("Not enrolled")
    except Exception:
        results["windows_insider"] = _ok("Not enrolled")

    return results


# ─── 2.9 GPU Settings ───────────────────────────────────────────────────────

def check_gpu_settings():
    results = {}

    # NVIDIA driver settings
    nvidia_key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
    try:
        nv_vals = list_reg_values(winreg.HKEY_LOCAL_MACHINE, nvidia_key)
        if nv_vals:
            results["nvidia_driver_settings"] = _ok(f"NVIDIA adapter found ({len(nv_vals)} registry entries)")
        else:
            results["nvidia_driver_settings"] = _ok("No NVIDIA adapter at standard path")
    except Exception:
        results["nvidia_driver_settings"] = _ok("Could not read NVIDIA settings")

    # G-Sync / FreeSync detection (best effort via registry)
    try:
        gsync_reg = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Power",
            "GSync",
            default=None
        )
        if gsync_reg is not None:
            results["gsync_freesync"] = _ok(f"G-Sync entry found in registry (value={gsync_reg})")
        else:
            results["gsync_freesync"] = _ok("G-Sync/FreeSync status not readable from registry (check in GPU control panel)")
    except Exception:
        results["gsync_freesync"] = _ok("Could not determine (check GPU control panel)")

    # NVIDIA low latency mode hint via NvCplDaemon or nv prefs
    results["nvidia_low_latency"] = _ok(
        "Check manually",
        "Set NVIDIA Control Panel > Manage 3D Settings > Low Latency Mode to 'Ultra' for competitive gaming."
    )

    results["gpu_power_management"] = _ok(
        "Check manually",
        "Set NVIDIA Control Panel > Manage 3D Settings > Power Management Mode to 'Prefer maximum performance'."
    )

    return results


# ─── 2.10 DirectX / Runtimes ────────────────────────────────────────────────

def check_directx_runtimes():
    results = {}

    # DirectX version
    try:
        dx_ver = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\DirectX",
            "Version",
            default=None
        )
        if dx_ver:
            results["directx_version"] = _ok(dx_ver)
        else:
            results["directx_version"] = _warn("N/A", "Could not read DirectX version from registry.")
    except Exception:
        results["directx_version"] = _warn("N/A", "Could not read DirectX version.")

    # .NET versions
    try:
        net_path = r"SOFTWARE\Microsoft\NET Framework Setup\NDP"
        subkeys = list_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, net_path)
        net_versions = []
        for sk in subkeys:
            ver = read_reg(
                winreg.HKEY_LOCAL_MACHINE,
                f"{net_path}\\{sk}",
                "Version",
                default=None
            )
            if ver:
                net_versions.append(ver)
            else:
                net_versions.append(sk)
        results["dotnet_versions"] = _ok(", ".join(net_versions) if net_versions else "None found")
    except Exception:
        results["dotnet_versions"] = _ok("Could not enumerate")

    # Visual C++ Redistributables
    try:
        vcredist_count = 0
        vcredist_versions = []
        vc_bases = [
            r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
            r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86",
            r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        ]
        for base in vc_bases:
            ver = read_reg(winreg.HKEY_LOCAL_MACHINE, base, "Version", default=None)
            if ver:
                vcredist_count += 1
                vcredist_versions.append(ver)

        # Also check Uninstall keys
        uninst_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        subkeys = list_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, uninst_path)
        for sk in subkeys:
            name = read_reg(winreg.HKEY_LOCAL_MACHINE, f"{uninst_path}\\{sk}", "DisplayName", default="")
            if "Visual C++" in (name or "") and "Redistributable" in (name or ""):
                vcredist_count += 1

        results["vcredist_installed"] = _ok(
            f"{vcredist_count} Visual C++ Redistributable(s) found"
        )
    except Exception:
        results["vcredist_installed"] = _ok("Could not enumerate")

    return results


# ─── 2.11 BIOS & Firmware ───────────────────────────────────────────────────

def check_bios_firmware(wmi_client, system_specs=None):
    results = {}

    # XMP/DOCP: compare configured speed vs max speed
    try:
        ram_rows = wmi_query(
            wmi_client,
            "SELECT Speed, ConfiguredClockSpeed FROM Win32_PhysicalMemory",
            ["Speed", "ConfiguredClockSpeed"]
        )
        if ram_rows:
            max_speeds = [int(r.get("Speed") or 0) for r in ram_rows if r.get("Speed")]
            cfg_speeds = [int(r.get("ConfiguredClockSpeed") or 0) for r in ram_rows if r.get("ConfiguredClockSpeed")]
            if max_speeds and cfg_speeds:
                max_spd = max(max_speeds)
                cfg_spd = max(cfg_speeds)
                if cfg_spd < max_spd * 0.9:
                    results["xmp_docp"] = _warn(
                        f"RAM running at {cfg_spd}MHz (rated {max_spd}MHz)",
                        f"RAM is not running at rated speed. Enable XMP/DOCP in BIOS to unlock {max_spd}MHz. Free performance!"
                    )
                else:
                    results["xmp_docp"] = _ok(f"RAM running at {cfg_spd}MHz (rated {max_spd}MHz)")
            else:
                results["xmp_docp"] = _ok("Could not compare RAM speeds")
        else:
            results["xmp_docp"] = _ok("Could not read RAM speed data")
    except Exception:
        results["xmp_docp"] = _ok("Could not determine XMP/DOCP status")

    # Resizable BAR
    try:
        rebar = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\HAL",
            "PciReBarEnabled",
            default=None
        )
        if rebar == 1:
            results["resizable_bar"] = _ok("Enabled")
        elif rebar == 0:
            results["resizable_bar"] = _warn(
                "Disabled",
                "Enable Resizable BAR (ReBAR/SAM) in BIOS for up to 10-15% GPU performance improvement."
            )
        else:
            results["resizable_bar"] = _ok("Status unknown (may still be active)")
    except Exception:
        results["resizable_bar"] = _ok("Could not determine")

    # Secure Boot
    try:
        sb = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
            "UEFISecureBootEnabled",
            default=None
        )
        if sb == 1:
            results["secure_boot"] = _ok("Enabled")
        elif sb == 0:
            results["secure_boot"] = _warn(
                "Disabled",
                "Secure Boot is disabled. Some anti-cheat software requires it. Enable in BIOS if needed."
            )
        else:
            results["secure_boot"] = _ok("Unknown/BIOS mode")
    except Exception:
        results["secure_boot"] = _ok("Could not determine")

    # BIOS age
    try:
        bios_rows = wmi_query(
            wmi_client,
            "SELECT ReleaseDate FROM Win32_BIOS",
            ["ReleaseDate"]
        )
        if bios_rows:
            rd = bios_rows[0].get("ReleaseDate") or ""
            if len(rd) >= 8:
                bios_dt = datetime.datetime(int(rd[0:4]), int(rd[4:6]), int(rd[6:8]))
                age_days = (datetime.datetime.now() - bios_dt).days
                if age_days > 730:
                    results["bios_age_days"] = _warn(
                        f"{age_days} days old ({rd[0:4]}-{rd[4:6]}-{rd[6:8]})",
                        "BIOS is over 2 years old. Check manufacturer website for updates with stability/performance improvements."
                    )
                else:
                    results["bios_age_days"] = _ok(f"{age_days} days old")
            else:
                results["bios_age_days"] = _ok("Could not parse date")
        else:
            results["bios_age_days"] = _ok("Could not read BIOS date")
    except Exception:
        results["bios_age_days"] = _ok("Could not determine BIOS age")

    # TPM
    try:
        tpm_rows = wmi_query(
            wmi_client,
            "SELECT IsEnabled_InitialValue FROM Win32_Tpm",
            ["IsEnabled_InitialValue"]
        )
        if tpm_rows:
            enabled = tpm_rows[0].get("IsEnabled_InitialValue")
            results["tpm"] = _ok("TPM Present and Enabled" if enabled else "TPM Present but Disabled")
        else:
            results["tpm"] = _ok("TPM not detected (may need WMI namespace root\\cimv2\\Security\\MicrosoftTpm)")
    except Exception:
        results["tpm"] = _ok("TPM status unknown")

    return results


# ─── 2.12 Display Issues ────────────────────────────────────────────────────

def check_display_issues(wmi_client):
    results = {}

    try:
        # Current refresh rate via WMI
        vid_rows = wmi_query(
            wmi_client,
            "SELECT CurrentRefreshRate, MaxRefreshRate, Name FROM Win32_VideoController",
            ["CurrentRefreshRate", "MaxRefreshRate", "Name"]
        )
        if vid_rows:
            r = vid_rows[0]
            current_rr = r.get("CurrentRefreshRate") or 0
            max_rr = r.get("MaxRefreshRate") or 0
            try:
                current_rr = int(current_rr)
                max_rr = int(max_rr)
            except Exception:
                pass

            if max_rr and current_rr and current_rr < max_rr:
                results["refresh_rate"] = _warn(
                    f"Current: {current_rr}Hz (Max: {max_rr}Hz)",
                    f"Display is not running at maximum refresh rate. Set to {max_rr}Hz in Display Settings > Advanced display."
                )
            elif current_rr:
                results["refresh_rate"] = _ok(f"{current_rr}Hz")
            else:
                results["refresh_rate"] = _ok("Could not determine refresh rate")
        else:
            results["refresh_rate"] = _ok("Could not read display info")
    except Exception:
        results["refresh_rate"] = _ok("Error reading display info")

    # Multi-monitor check
    try:
        import ctypes
        monitor_count = ctypes.windll.user32.GetSystemMetrics(80)  # SM_CMONITORS
        if monitor_count > 1:
            results["multi_monitor"] = _warn(
                f"{monitor_count} monitors detected",
                "Multiple monitors can reduce GPU performance. Disconnect unused monitors while gaming."
            )
        else:
            results["multi_monitor"] = _ok(f"{monitor_count} monitor")
    except Exception:
        results["multi_monitor"] = _ok("Could not determine monitor count")

    results["gsync_freesync"] = _ok(
        "Check manually",
        "Enable G-Sync or FreeSync in GPU control panel and monitor OSD for tear-free gaming."
    )

    return results


# ─── Main entry point ───────────────────────────────────────────────────────

def run_fps_diagnosis(system_specs=None):
    """Phase 2 — exhaustive FPS loss checks. Returns a dict with sections."""
    wmi_client = get_wmi_client()

    diagnosis = {
        "driver_issues": check_driver_issues(wmi_client),
        "background_processes": check_background_processes(),
        "thermal_power": check_thermal_power(),
        "memory_issues": check_memory_issues(),
        "storage_issues": check_storage_issues(),
        "network_issues": check_network_issues(),
        "software_overlays": check_software_overlays(),
        "windows_settings": check_windows_settings(),
        "gpu_settings": check_gpu_settings(),
        "directx_runtimes": check_directx_runtimes(),
        "bios_firmware": check_bios_firmware(wmi_client, system_specs),
        "display_issues": check_display_issues(wmi_client),
    }

    return diagnosis
