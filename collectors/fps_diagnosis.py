"""Phase 2: Exhaustive FPS loss checks."""

import subprocess
import socket
import time
import os
import ctypes
import tempfile
import winreg
import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

from utils.wmi_helpers import get_wmi_client, get_wmi_client_ns, wmi_query
from utils.registry import read_reg, reg_key_exists, list_reg_subkeys, list_reg_values
from utils.known_issues import (
    FPS_KILLER_PROCESSES, PROBLEMATIC_SERVICES, KNOWN_BAD_DRIVER_VERSIONS, OVERLAY_PROCESSES,
    KNOWN_BAD_AUDIO_DRIVERS, KNOWN_BAD_NETWORK_DRIVERS,
)


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
    rows = []
    try:
        rows = wmi_query(
            wmi_client,
            "SELECT DriverDate, DriverVersion, Name FROM Win32_VideoController",
            ["DriverDate", "DriverVersion", "Name"]
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

    # GPU driver version advisory against known bad versions (proper version parsing)
    try:
        if rows:
            driver_ver = str(rows[0].get("DriverVersion") or "")
            gpu_name = str(rows[0].get("Name") or "").lower()
            advisory = None
            if "nvidia" in gpu_name or "geforce" in gpu_name:
                # NVIDIA WDDM driver format: aa.bb.cc.dddd → branch = last two segments
                # e.g., 31.0.15.5263 → 552.63, 31.0.15.2686 → 526.86
                nv_branch = ""
                try:
                    parts = driver_ver.split(".")
                    if len(parts) >= 4:
                        nv_branch = parts[-2][-1] + parts[-1]  # e.g., "5" + "2686" → "52686"
                        nv_major = int(nv_branch[:3])  # e.g., 526
                    elif len(parts) >= 2:
                        nv_major = int(parts[0])
                    else:
                        nv_major = 0
                except (ValueError, IndexError):
                    nv_major = 0
                if 526 <= nv_major < 527:
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("nvidia_526", "")
                elif 512 <= nv_major < 513:
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("nvidia_512", "")
                elif 551 <= nv_major < 552:
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("nvidia_551", "")
                elif 552 <= nv_major < 553:
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("nvidia_552", "")
                elif 546 <= nv_major < 547:
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("nvidia_546", "")
            elif "amd" in gpu_name or "radeon" in gpu_name:
                # AMD driver versions: check major.minor from WDDM string
                try:
                    parts = driver_ver.split(".")
                    if len(parts) >= 4:
                        amd_suffix = parts[-2] + "." + parts[-1]
                    else:
                        amd_suffix = driver_ver
                except Exception:
                    amd_suffix = driver_ver
                if amd_suffix.startswith("24.1"):
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("amd_24_1", "")
                elif amd_suffix.startswith("24.2"):
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("amd_24_2", "")
                elif amd_suffix.startswith("23.12"):
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("amd_23_12", "")
                elif any(amd_suffix.startswith(p) for p in ["22.", "22_"]):
                    advisory = KNOWN_BAD_DRIVER_VERSIONS.get("amd_notes", "")
            elif "intel" in gpu_name and "arc" in gpu_name:
                try:
                    parts = driver_ver.split(".")
                    if len(parts) >= 2:
                        ver_num = int(parts[-1]) if parts[-1].isdigit() else 0
                        if ver_num <= 4032:
                            advisory = KNOWN_BAD_DRIVER_VERSIONS.get("intel_arc_101_4032", "")
                        elif ver_num == 4502:
                            advisory = KNOWN_BAD_DRIVER_VERSIONS.get("intel_arc_101_4502", "")
                except (ValueError, IndexError):
                    pass
            if advisory:
                results["gpu_driver_version_advisory"] = _warn(driver_ver, advisory)
            elif driver_ver and driver_ver != "N/A":
                results["gpu_driver_version_advisory"] = _ok(driver_ver)
    except Exception:
        pass

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
                        "savservice.exe", "esets_daemon.exe"]
        found_av = [p["name"] for p in all_procs if p["name"].lower() in av_processes]
        if found_av:
            results["third_party_antivirus"] = _warn(
                f"Found: {', '.join(found_av)}",
                "Third-party AV can cause significant performance overhead. Add game executables to exclusions."
            )
        else:
            results["third_party_antivirus"] = _ok("None detected")

        # Process count by category
        try:
            _SYSTEM_PROCS = {"system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                             "lsass.exe", "services.exe", "svchost.exe", "dwm.exe", "explorer.exe",
                             "conhost.exe", "audiodg.exe", "ntoskrnl.exe", "registry"}
            _BROWSER_PROCS = {"chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe",
                              "vivaldi.exe", "iexplore.exe"}
            _GAME_CLIENT_PROCS = {"steam.exe", "epicgameslauncher.exe", "battle.net.exe",
                                  "uplaylaunch.exe", "eadesktop.exe", "riotclientservices.exe", "origin.exe"}
            counts = {"System": 0, "Browser": 0, "Game Client": 0, "Background": 0}
            for p in all_procs:
                n = p["name"].lower()
                if n in _SYSTEM_PROCS:
                    counts["System"] += 1
                elif n in _BROWSER_PROCS:
                    counts["Browser"] += 1
                elif n in _GAME_CLIENT_PROCS:
                    counts["Game Client"] += 1
                else:
                    counts["Background"] += 1
            results["process_categories"] = _ok(
                f"Sys:{counts['System']}  Browser:{counts['Browser']}  GameClient:{counts['Game Client']}  BG:{counts['Background']}"
            )
        except Exception:
            pass

    except Exception as e:
        results["process_check_error"] = _warn(f"Error: {e}", "Could not complete process analysis.")

    # SysMain service check
    try:
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

    # System uptime warning
    if PSUTIL_OK:
        try:
            uptime_days = (datetime.datetime.now().timestamp() - psutil.boot_time()) / 86400
            if uptime_days > 7:
                results["system_uptime"] = _warn(
                    f"{uptime_days:.1f} days",
                    f"System has been running {uptime_days:.0f} days without a restart. Reboot to clear memory leaks and apply pending updates."
                )
            else:
                results["system_uptime"] = _ok(f"{uptime_days:.1f} days since last boot")
        except Exception:
            pass

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

    # RAM total capacity grading
    try:
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        if total_gb < 8:
            results["ram_total_capacity"] = _crit(
                f"{total_gb:.1f}GB installed",
                "Less than 8GB RAM is insufficient for modern games. Many titles require 8-16GB minimum."
            )
        elif total_gb < 16:
            results["ram_total_capacity"] = _warn(
                f"{total_gb:.1f}GB installed",
                "8-15GB RAM may cause performance issues in modern titles that require 16GB. Upgrade when possible."
            )
        elif total_gb >= 32:
            results["ram_total_capacity"] = _ok(f"{total_gb:.1f}GB installed (excellent)")
        else:
            results["ram_total_capacity"] = _ok(f"{total_gb:.1f}GB installed")
    except Exception:
        pass

    try:
        swap = psutil.swap_memory()
        if swap.total > 0:
            swap_pct = swap.percent
            if swap_pct > 50:
                results["pagefile_usage"] = _warn(
                    f"{swap_pct:.1f}% ({swap.used / (1024**3):.1f}GB used)",
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
        wmi_client = get_wmi_client()
        os_rows = wmi_query(
            wmi_client,
            "SELECT TotalPhysicalMemory, TotalVirtualMemorySize FROM Win32_OperatingSystem",
            ["TotalPhysicalMemory", "TotalVirtualMemorySize"]
        )
        if os_rows and PSUTIL_OK:
            reported_bytes = int(os_rows[0].get("TotalPhysicalMemory") or 0)
            actual = psutil.virtual_memory().total
            diff_gb = (reported_bytes - actual) / (1024 ** 3) if reported_bytes > 0 else 0
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

def _disk_io_benchmark():
    """16MB sequential read/write benchmark. Returns (read_mbps, write_mbps) or (None, None)."""
    block_size = 4 * 1024 * 1024  # 4MB
    num_blocks = 4  # 16MB total
    total_mb = block_size * num_blocks / (1024 * 1024)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as f:
            tmp_path = f.name
            block = b"\x00" * block_size
            t0 = time.time()
            for _ in range(num_blocks):
                f.write(block)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        write_time = time.time() - t0

        t0 = time.time()
        with open(tmp_path, "rb") as f:
            while f.read(block_size):
                pass
        read_time = time.time() - t0

        os.unlink(tmp_path)
        return (
            round(total_mb / read_time, 1) if read_time > 0 else None,
            round(total_mb / write_time, 1) if write_time > 0 else None,
        )
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return None, None


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
                            f"{pct_free:.1f}% free ({int(usage.free // (1024**3))}GB)",
                            f"Drive {drive_letter} is critically full. Free at least 15% for optimal performance."
                        )
                    elif pct_free < 15:
                        results[key] = _warn(
                            f"{pct_free:.1f}% free ({int(usage.free // (1024**3))}GB)",
                            f"Drive {drive_letter} has low free space. Windows needs 15%+ for proper operation."
                        )
                    else:
                        results[key] = _ok(f"{pct_free:.1f}% free")
                except Exception:
                    pass
        except Exception:
            results["disk_space_error"] = _warn("Error", "Could not check disk space.")

    # Quick disk I/O benchmark
    try:
        read_mbps, write_mbps = _disk_io_benchmark()
        if read_mbps is not None and write_mbps is not None:
            if read_mbps < 100:
                results["disk_sequential_read"] = _warn(
                    f"{read_mbps} MB/s",
                    "Very slow sequential read speed. Expected: HDD ~100+ MB/s, SATA SSD ~500+ MB/s, NVMe ~1000+ MB/s."
                )
            else:
                results["disk_sequential_read"] = _ok(f"{read_mbps} MB/s read, {write_mbps} MB/s write")
        else:
            results["disk_sequential_read"] = _ok("Could not benchmark (temp file error)")
    except Exception:
        pass

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

    # BitLocker detection
    try:
        bde_out = _run(["manage-bde", "-status"], "")
        if bde_out and "Protection On" in bde_out:
            results["bitlocker"] = _warn(
                "Enabled on one or more drives",
                "BitLocker encryption adds I/O overhead. Consider disabling on game drives (HDDs/older SSDs) for better load times."
            )
        elif bde_out:
            results["bitlocker"] = _ok("Not active")
    except Exception:
        pass

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
        ping_out = _run(["ping", "-n", "2", "-w", "1000", "8.8.8.8"], "")
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

    # Check against full OVERLAY_PROCESSES list
    found_overlays = [name for name in OVERLAY_PROCESSES if name.lower() in running_procs]
    if found_overlays:
        preview = ", ".join(found_overlays[:5])
        suffix = f"... (+{len(found_overlays) - 5} more)" if len(found_overlays) > 5 else ""
        results["overlay_processes"] = _warn(
            f"Running: {preview}{suffix}",
            f"Overlay/injection processes active. Disable in-game overlays while gaming: {', '.join(found_overlays[:3])}."
        )
    else:
        results["overlay_processes"] = _ok("No known overlay processes running")

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

    # Hyper-V — parse only the hypervisorlaunchtype line to avoid false positives
    try:
        hyperv_output = _run(["bcdedit", "/enum"], "")
        hyperv_line = ""
        for line in hyperv_output.splitlines():
            if "hypervisorlaunchtype" in line.lower():
                hyperv_line = line.lower()
                break
        if hyperv_line:
            if "auto" in hyperv_line:
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

    # Timer resolution
    try:
        ntdll = ctypes.WinDLL("ntdll.dll")
        minimum = ctypes.c_ulong()
        maximum = ctypes.c_ulong()
        current = ctypes.c_ulong()
        ntdll.NtQueryTimerResolution(ctypes.byref(minimum), ctypes.byref(maximum), ctypes.byref(current))
        current_ms = current.value / 10000
        if current_ms > 5.0:
            results["timer_resolution"] = _warn(
                f"{current_ms:.1f}ms (default 15.6ms)",
                "System timer is at default 15.6ms resolution. Games set it to 1ms automatically; if stuttering occurs, use TimerResolution tool."
            )
        else:
            results["timer_resolution"] = _ok(f"{current_ms:.1f}ms (high-res active)")
    except Exception:
        pass

    # Delivery Optimization
    try:
        do_mode = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\DeliveryOptimization\Config",
            "DODownloadMode",
            default=None
        )
        if do_mode in (3, 100):
            results["delivery_optimization"] = _warn(
                f"Mode={do_mode} (internet sharing)",
                "Windows is using your bandwidth to share updates with other PCs on the internet. Set to LAN-only in Settings > Windows Update > Advanced > Delivery Optimization."
            )
        elif do_mode == 0:
            results["delivery_optimization"] = _ok("Disabled")
        elif do_mode == 1:
            results["delivery_optimization"] = _ok("LAN-only")
        else:
            results["delivery_optimization"] = _ok(f"Mode={do_mode}")
    except Exception:
        pass

    # Shader Cache (D3DSCache directory as proxy)
    try:
        d3d_cache_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "D3DSCache")
        if os.path.isdir(d3d_cache_path):
            results["shader_cache"] = _ok("DirectX shader cache active (D3DSCache present)")
        else:
            results["shader_cache"] = _warn(
                "D3DSCache folder absent",
                "DirectX shader cache may be disabled or unused. Shader caching prevents first-encounter stutter."
            )
    except Exception:
        pass

    # Pending Reboot
    try:
        pending = False
        pending_keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"),
        ]
        for hive, key in pending_keys:
            if reg_key_exists(hive, key):
                pending = True
                break
        if not pending:
            pfro = read_reg(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager",
                "PendingFileRenameOperations",
                default=None
            )
            if pfro:
                pending = True
        if pending:
            results["pending_reboot"] = _warn(
                "Reboot pending",
                "Windows is waiting for a reboot to finish updates. Pending reboots can degrade performance. Restart your PC."
            )
        else:
            results["pending_reboot"] = _ok("No pending reboot")
    except Exception:
        pass

    # Scheduled Tasks — check for known heavy tasks
    try:
        heavy_tasks = [
            ("\\Microsoft\\Windows\\Defrag\\ScheduledDefrag", "Disk Defragmentation"),
            ("\\Microsoft\\Windows\\Application Experience\\ProgramDataUpdater", "App Compat Telemetry"),
            ("\\Microsoft\\Windows\\Customer Experience Improvement Program\\Consolidator", "CEIP Consolidator"),
            ("\\Microsoft\\Windows\\WindowsUpdate\\Automatic App Update", "Windows Store Auto Update"),
        ]
        active_heavy = []
        for task_path, task_name in heavy_tasks:
            out = _run(["schtasks", "/query", "/tn", task_path, "/fo", "LIST"], "")
            if out and "Status:" in out:
                for line in out.split("\n"):
                    if "Status:" in line and "Disabled" not in line and "Ready" in line:
                        active_heavy.append(task_name)
                        break
        if active_heavy:
            results["scheduled_tasks"] = _warn(
                f"Active: {', '.join(active_heavy)}",
                "Heavy scheduled tasks are enabled. They may fire during gameplay. Review in Task Scheduler."
            )
        else:
            results["scheduled_tasks"] = _ok("No problematic scheduled tasks found")
    except Exception:
        pass

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

    # TPM — Win32_Tpm lives in root\cimv2\Security\MicrosoftTpm, not default root\cimv2
    try:
        tpm_client = get_wmi_client_ns(r"root\cimv2\Security\MicrosoftTpm")
        tpm_rows = wmi_query(
            tpm_client,
            "SELECT IsEnabled_InitialValue FROM Win32_Tpm",
            ["IsEnabled_InitialValue"]
        )
        if tpm_rows:
            enabled = tpm_rows[0].get("IsEnabled_InitialValue")
            results["tpm"] = _ok("TPM Present and Enabled" if enabled else "TPM Present but Disabled")
        else:
            results["tpm"] = _ok("TPM not detected via WMI")
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

    # DPI scaling check
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        scaling_pct = round(dpi / 96 * 100)
        if scaling_pct > 100:
            results["dpi_scaling"] = _warn(
                f"{scaling_pct}% scaling",
                f"Display scaling is {scaling_pct}%. Values above 100% can affect game rendering. Set to 100% in Display Settings > Scale if games look wrong."
            )
        else:
            results["dpi_scaling"] = _ok(f"{scaling_pct}% (100% recommended)")
    except Exception:
        pass

    return results


# ─── 2.13 Startup Programs ──────────────────────────────────────────────────

def check_startup_programs():
    results = {}

    startup_entries = []
    run_paths = [
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
    ]
    for hive, path in run_paths:
        try:
            values = list_reg_values(hive, path)
            for name, value in values.items():
                startup_entries.append({"name": name, "command": str(value)})
        except Exception:
            pass

    try:
        startup_folder = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        if os.path.isdir(startup_folder):
            for f in os.listdir(startup_folder):
                if not f.startswith("."):
                    startup_entries.append({"name": f, "command": f"Startup folder: {f}"})
    except Exception:
        pass

    fps_killers_in_startup = []
    for entry in startup_entries:
        cmd = entry["command"].lower()
        for killer_proc in FPS_KILLER_PROCESSES:
            if killer_proc.lower() in cmd:
                fps_killers_in_startup.append(entry["name"])
                break

    total = len(startup_entries)
    if total > 20:
        results["startup_count"] = _warn(
            f"{total} programs",
            "Excessive startup programs. Open Task Manager > Startup and disable non-essential entries."
        )
    elif total > 10:
        results["startup_count"] = _warn(
            f"{total} programs",
            "Many startup programs detected. Disable unnecessary entries to reduce boot time and background overhead."
        )
    else:
        results["startup_count"] = _ok(f"{total} programs")

    if fps_killers_in_startup:
        results["fps_killers_in_startup"] = _warn(
            f"Found: {', '.join(fps_killers_in_startup[:3])}",
            "Known FPS-impacting programs auto-start on boot. Disable them in Task Manager > Startup tab."
        )
    else:
        results["fps_killers_in_startup"] = _ok("None detected")

    return results


# ─── 2.14 DPC Latency ───────────────────────────────────────────────────────

def _measure_dpc(wmi_client):
    """Measure DPC rate with 1-second sleep in a thread-safe way."""
    try:
        rows1 = wmi_query(
            wmi_client,
            "SELECT DPCsQueuedPersec FROM Win32_PerfRawData_PerfOS_Processor WHERE Name='_Total'",
            ["DPCsQueuedPersec"]
        )
        t1 = time.time()
        time.sleep(1)
        rows2 = wmi_query(
            wmi_client,
            "SELECT DPCsQueuedPersec FROM Win32_PerfRawData_PerfOS_Processor WHERE Name='_Total'",
            ["DPCsQueuedPersec"]
        )
        elapsed = time.time() - t1
        if rows1 and rows2 and elapsed > 0:
            d1 = int(rows1[0].get("DPCsQueuedPersec") or 0)
            d2 = int(rows2[0].get("DPCsQueuedPersec") or 0)
            return max(0, d2 - d1) / elapsed
    except Exception:
        pass
    return None


def check_dpc_latency(wmi_client):
    results = {}
    try:
        # Run the blocking DPC measurement in a thread pool to avoid blocking main thread
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_measure_dpc, wmi_client)
            dpc_rate = future.result(timeout=10)

        if dpc_rate is not None:
            if dpc_rate > 10000:
                results["dpc_rate"] = _warn(
                    f"{dpc_rate:.0f} DPCs/sec",
                    "High DPC interrupt rate. This causes audio glitches and micro-stutters. Use LatencyMon to identify the offending driver."
                )
            else:
                results["dpc_rate"] = _ok(f"{dpc_rate:.0f} DPCs/sec")
        else:
            results["dpc_rate"] = _ok("Could not measure")
    except Exception:
        results["dpc_rate"] = _ok("Could not measure DPC rate")
    return results


# ─── 2.15 Problematic Services ──────────────────────────────────────────────

def check_problematic_services(wmi_client):
    results = {}
    try:
        svc_rows = wmi_query(
            wmi_client,
            "SELECT Name FROM Win32_Service WHERE State='Running'",
            ["Name"]
        )
        running_names = {(r.get("Name") or "").strip() for r in svc_rows}
        found = [(name, desc) for name, desc in PROBLEMATIC_SERVICES.items() if name in running_names]
        if found:
            preview = ", ".join(s[0] for s in found[:4])
            suffix = f"... (+{len(found) - 4} more)" if len(found) > 4 else ""
            results["problematic_services"] = _warn(
                f"{len(found)} found: {preview}{suffix}",
                "Services impacting performance: " + "; ".join(
                    f"{s[0]}" for s in found[:3]
                ) + ". Disable unneeded ones via services.msc."
            )
        else:
            results["problematic_services"] = _ok("No known problematic services running")
    except Exception:
        results["problematic_services"] = _warn("Could not enumerate", "WMI service query failed.")
    return results


# ─── 2.16 Windows Event Log Errors ──────────────────────────────────────────

def check_event_log_errors():
    results = {}

    def _whea():
        try:
            out = _run([
                "wevtutil", "qe", "System",
                "/q:*[System[Provider[@Name='Microsoft-Windows-WHEA-Logger'] and (EventID>=17 and EventID<=20)]]",
                "/c:5", "/rd:true", "/f:text"
            ], "")
            if out and "Event[" in out:
                return {"whea_hardware_errors": _crit(
                    "WHEA errors in event log",
                    "Hardware errors detected. This indicates faulty RAM, CPU, or motherboard. Run mdsched.exe (Windows Memory Diagnostic)."
                )}
            return {"whea_hardware_errors": _ok("No recent WHEA hardware errors")}
        except Exception:
            return {"whea_hardware_errors": _ok("Could not query event log")}

    def _display_driver():
        try:
            out = _run([
                "wevtutil", "qe", "System",
                "/q:*[System[Provider[@Name='Display'] and EventID=4101]]",
                "/c:5", "/rd:true", "/f:text"
            ], "")
            if out and "Event[" in out:
                return {"display_driver_crashes": _warn(
                    "GPU driver crashes in event log",
                    "GPU driver has crashed recently (nvlddmkm/atikmpag). Update GPU drivers or check GPU temperatures and stability."
                )}
            return {"display_driver_crashes": _ok("No recent display driver crashes")}
        except Exception:
            return {"display_driver_crashes": _ok("Could not query event log")}

    def _kernel_power():
        try:
            out = _run([
                "wevtutil", "qe", "System",
                "/q:*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=41]]",
                "/c:5", "/rd:true", "/f:text"
            ], "")
            if out and "Event[" in out:
                return {"kernel_power_events": _warn(
                    "Unexpected shutdown events detected",
                    "System experienced unexpected shutdowns/restarts (Event ID 41). Check PSU, overclocking stability, and temperatures."
                )}
            return {"kernel_power_events": _ok("No recent unexpected shutdown events")}
        except Exception:
            return {"kernel_power_events": _ok("Could not query event log")}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_whea), executor.submit(_display_driver), executor.submit(_kernel_power)]
        for f in futures:
            results.update(f.result())

    return results


# ─── 2.17 Deep Driver Analysis ──────────────────────────────────────────────

def check_deep_driver_analysis(wmi_client):
    results = {}

    # Full driver enumeration — flag outdated (>2 years) and unsigned drivers
    try:
        driver_rows = wmi_query(
            wmi_client,
            "SELECT DeviceName, DriverVersion, DriverDate, IsSigned, DriverProviderName "
            "FROM Win32_PnPSignedDriver WHERE DriverVersion IS NOT NULL",
            ["DeviceName", "DriverVersion", "DriverDate", "IsSigned", "DriverProviderName"]
        )
        outdated = []
        unsigned = []
        now = datetime.datetime.now()
        two_years_ago = now - datetime.timedelta(days=730)

        for drv in driver_rows:
            name = drv.get("DeviceName") or "Unknown"
            dd = str(drv.get("DriverDate") or "")
            signed = drv.get("IsSigned")

            # Check outdated
            if len(dd) >= 8:
                try:
                    drv_dt = datetime.datetime(int(dd[0:4]), int(dd[4:6]), int(dd[6:8]))
                    if drv_dt < two_years_ago:
                        outdated.append(name[:40])
                except (ValueError, IndexError):
                    pass

            # Check unsigned
            if signed is False or signed == 0:
                unsigned.append(name[:40])

        if outdated:
            results["outdated_drivers"] = _warn(
                f"{len(outdated)} driver(s) >2 years old",
                f"Outdated drivers: {', '.join(outdated[:3])}. Update via Device Manager or manufacturer website."
            )
        else:
            results["outdated_drivers"] = _ok("All drivers reasonably current")

        if unsigned:
            results["unsigned_drivers"] = _warn(
                f"{len(unsigned)} unsigned driver(s)",
                f"Unsigned drivers: {', '.join(unsigned[:3])}. May cause stability issues or be blocked by HVCI."
            )
        else:
            results["unsigned_drivers"] = _ok("All drivers are signed")

    except Exception:
        results["driver_enumeration"] = _ok("Could not enumerate all drivers")

    # Audio driver check against known bad audio drivers
    try:
        audio_rows = wmi_query(
            wmi_client,
            "SELECT DeviceName, DriverVersion, DriverProviderName FROM Win32_PnPSignedDriver "
            "WHERE DeviceClass = 'MEDIA'",
            ["DeviceName", "DriverVersion", "DriverProviderName"]
        )
        audio_issues = []
        for drv in audio_rows:
            name = str(drv.get("DeviceName") or "").lower()
            ver = str(drv.get("DriverVersion") or "")
            provider = str(drv.get("DriverProviderName") or "").lower()

            for key, info in KNOWN_BAD_AUDIO_DRIVERS.items():
                vendor_lower = info["vendor"].lower()
                if vendor_lower in name or vendor_lower in provider:
                    if info["bad_versions"]:
                        if any(ver.startswith(bv) for bv in info["bad_versions"]):
                            audio_issues.append(info["description"])
                    else:
                        audio_issues.append(info["description"])
                    break

        if audio_issues:
            results["audio_driver_issues"] = _warn(
                f"{len(audio_issues)} audio driver issue(s)",
                audio_issues[0][:120]
            )
        else:
            results["audio_driver_issues"] = _ok("No known audio driver issues")
    except Exception:
        results["audio_driver_issues"] = _ok("Could not check audio drivers")

    # Network driver check against known bad network drivers
    try:
        net_rows = wmi_query(
            wmi_client,
            "SELECT DeviceName, DriverVersion, DriverProviderName FROM Win32_PnPSignedDriver "
            "WHERE DeviceClass = 'NET'",
            ["DeviceName", "DriverVersion", "DriverProviderName"]
        )
        net_issues = []
        for drv in net_rows:
            name = str(drv.get("DeviceName") or "").lower()
            for key, info in KNOWN_BAD_NETWORK_DRIVERS.items():
                if any(mn in name for mn in info["match_names"]):
                    net_issues.append(info["description"])
                    break

        if net_issues:
            results["network_driver_issues"] = _warn(
                f"{len(net_issues)} network driver concern(s)",
                net_issues[0][:120]
            )
        else:
            results["network_driver_issues"] = _ok("No known network driver issues")
    except Exception:
        results["network_driver_issues"] = _ok("Could not check network drivers")

    # USB controller driver check — generic USB3 drivers cause input lag
    try:
        usb_rows = wmi_query(
            wmi_client,
            "SELECT DeviceName, DriverProviderName FROM Win32_PnPSignedDriver "
            "WHERE DeviceClass = 'USB' AND DriverProviderName = 'Microsoft'",
            ["DeviceName", "DriverProviderName"]
        )
        usb3_generic = [r for r in usb_rows if "usb 3" in str(r.get("DeviceName") or "").lower()
                        or "xhci" in str(r.get("DeviceName") or "").lower()]
        if usb3_generic:
            results["usb_controller_drivers"] = _warn(
                f"{len(usb3_generic)} USB3 controller(s) using generic Microsoft drivers",
                "Generic USB3 drivers can cause input lag. Install manufacturer's USB3/xHCI drivers."
            )
        else:
            results["usb_controller_drivers"] = _ok("USB controllers using proper drivers")
    except Exception:
        results["usb_controller_drivers"] = _ok("Could not check USB drivers")

    return results


# ─── 2.18 IRQ & Interrupt Analysis ──────────────────────────────────────────

def check_irq_analysis(wmi_client):
    results = {}

    try:
        irq_rows = wmi_query(
            wmi_client,
            "SELECT IRQNumber FROM Win32_IRQResource",
            ["IRQNumber"]
        )
        if irq_rows:
            irq_counts = {}
            for row in irq_rows:
                irq = row.get("IRQNumber")
                if irq is not None:
                    irq_counts[irq] = irq_counts.get(irq, 0) + 1

            shared = {k: v for k, v in irq_counts.items() if v > 1}
            if shared:
                results["irq_sharing_conflicts"] = _warn(
                    f"{len(shared)} IRQ(s) shared by multiple devices",
                    "IRQ sharing can cause latency spikes. Check Device Manager for IRQ conflicts. Modern APIC systems usually handle this fine."
                )
            else:
                results["irq_sharing_conflicts"] = _ok("No IRQ sharing detected")
        else:
            results["irq_sharing_conflicts"] = _ok("Could not enumerate IRQ resources")
    except Exception:
        results["irq_sharing_conflicts"] = _ok("Could not query IRQ resources")

    # ISR (Interrupt Service Routine) rate check
    try:
        isr_rows1 = wmi_query(
            wmi_client,
            "SELECT InterruptsPersec FROM Win32_PerfRawData_PerfOS_Processor WHERE Name='_Total'",
            ["InterruptsPersec"]
        )
        if isr_rows1:
            isr_val = int(isr_rows1[0].get("InterruptsPersec") or 0)
            # Single-sample value from perf counter (approximation)
            if isr_val > 50000:
                results["isr_rate"] = _warn(
                    f"High interrupt count ({isr_val})",
                    "High interrupt rate detected. A misbehaving driver may be flooding the system with interrupts. Use LatencyMon to identify it."
                )
            else:
                results["isr_rate"] = _ok(f"Interrupt count: {isr_val} (normal)")
        else:
            results["isr_rate"] = _ok("Could not measure ISR rate")
    except Exception:
        results["isr_rate"] = _ok("Could not measure ISR rate")

    return results


# ─── 2.19 Windows Update & Patch Status ─────────────────────────────────────

def check_windows_update_status(wmi_client):
    results = {}

    try:
        qfe_rows = wmi_query(
            wmi_client,
            "SELECT HotFixID, InstalledOn FROM Win32_QuickFixEngineering",
            ["HotFixID", "InstalledOn"]
        )
        if qfe_rows:
            latest_date = None
            for row in qfe_rows:
                installed = str(row.get("InstalledOn") or "")
                if installed:
                    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                        try:
                            dt = datetime.datetime.strptime(installed, fmt)
                            if latest_date is None or dt > latest_date:
                                latest_date = dt
                            break
                        except ValueError:
                            continue

            if latest_date:
                days_since = (datetime.datetime.now() - latest_date).days
                if days_since > 90:
                    results["last_update_age"] = _warn(
                        f"{days_since} days since last update ({latest_date.strftime('%Y-%m-%d')})",
                        "System hasn't been updated in >90 days. Missing security and performance patches. Run Windows Update."
                    )
                else:
                    results["last_update_age"] = _ok(
                        f"Last updated {days_since} days ago ({latest_date.strftime('%Y-%m-%d')})"
                    )
            else:
                results["last_update_age"] = _ok("Could not determine last update date")

            results["installed_updates_count"] = _ok(f"{len(qfe_rows)} hotfix(es) installed")
        else:
            results["last_update_age"] = _ok("No update history available via WMI")
    except Exception:
        results["last_update_age"] = _ok("Could not query update history")

    # Check for pending feature update
    try:
        pending_update = reg_key_exists(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
        )
        downloading = False
        try:
            wu_procs = [p for p in (psutil.process_iter(["name"]) if PSUTIL_OK else [])
                        if (p.info.get("name") or "").lower() in ("wuauclt.exe", "tiworker.exe", "waasmedic.exe")]
            downloading = len(wu_procs) > 0
        except Exception:
            pass

        if pending_update:
            results["pending_feature_update"] = _warn(
                "Update pending reboot",
                "A Windows update is waiting for reboot. Restart to apply and avoid performance degradation."
            )
        elif downloading:
            results["pending_feature_update"] = _warn(
                "Update downloading/installing",
                "Windows Update is actively downloading. This may degrade performance temporarily."
            )
        else:
            results["pending_feature_update"] = _ok("No pending updates detected")
    except Exception:
        results["pending_feature_update"] = _ok("Could not check pending updates")

    return results


# ─── 2.20 Virtual Memory & Pagefile Config ───────────────────────────────────

def check_virtual_memory_config():
    results = {}

    if not PSUTIL_OK:
        return {"error": _warn("psutil unavailable", "Install psutil.")}

    try:
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        ram_gb = vm.total / (1024 ** 3)

        if swap.total > 0:
            pagefile_gb = swap.total / (1024 ** 3)
            ratio = pagefile_gb / ram_gb if ram_gb > 0 else 0

            if ratio < 0.5:
                results["pagefile_size_ratio"] = _warn(
                    f"Pagefile: {pagefile_gb:.1f}GB / RAM: {ram_gb:.1f}GB (ratio: {ratio:.2f}x)",
                    "Pagefile is very small relative to RAM. Increase to 1.5x RAM for gaming stability."
                )
            elif ratio > 3.0:
                results["pagefile_size_ratio"] = _warn(
                    f"Pagefile: {pagefile_gb:.1f}GB / RAM: {ram_gb:.1f}GB (ratio: {ratio:.2f}x)",
                    "Pagefile is unusually large. System-managed is usually fine for gaming."
                )
            else:
                results["pagefile_size_ratio"] = _ok(
                    f"Pagefile: {pagefile_gb:.1f}GB / RAM: {ram_gb:.1f}GB (ratio: {ratio:.2f}x)"
                )
        else:
            results["pagefile_size_ratio"] = _warn(
                "No pagefile",
                "No pagefile configured. This can cause crashes in memory-intensive games. Enable system-managed pagefile."
            )

        # Detect system-managed vs fixed pagefile
        try:
            pf_info = _run(["wmic", "pagefile", "list", "brief"], "")
            if pf_info and "pagefile.sys" in pf_info.lower():
                results["pagefile_management"] = _ok("Pagefile configured")
            else:
                results["pagefile_management"] = _ok("Pagefile status checked")
        except Exception:
            pass

        # Check if pagefile is on SSD vs HDD
        try:
            pf_output = _run(["wmic", "pagefile", "get", "Name"], "")
            if pf_output:
                pf_drive = ""
                for line in pf_output.splitlines():
                    line = line.strip()
                    if ":" in line and "Name" not in line:
                        pf_drive = line[:2]
                        break
                if pf_drive:
                    # Simple heuristic: we just report the drive letter
                    results["pagefile_drive"] = _ok(f"Pagefile on {pf_drive} drive")
        except Exception:
            pass

    except Exception as e:
        results["pagefile_config_error"] = _warn(f"Error: {e}", "Could not analyze pagefile config.")

    return results


# ─── 2.21 Audio Subsystem Issues ────────────────────────────────────────────

def check_audio_subsystem():
    results = {}

    # Check for audio enhancements enabled
    try:
        # Detect audio processing software running
        audio_enhancers = {
            "nahimicservice.exe": "Nahimic",
            "nahimicsvc32.exe": "Nahimic (32-bit)",
            "nahimicsvc64.exe": "Nahimic (64-bit)",
            "sonicstudiomonitor.exe": "Sonic Studio",
            "dtssoundunbound.exe": "DTS Sound",
            "wavessyssvc64.exe": "Waves MaxxAudio",
            "fxsvc.exe": "Sonic Radar",
        }
        found_enhancers = []
        if PSUTIL_OK:
            for proc in psutil.process_iter(["name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if pname in audio_enhancers:
                        found_enhancers.append(audio_enhancers[pname])
                except Exception:
                    continue

        if found_enhancers:
            results["audio_enhancement_software"] = _warn(
                f"Running: {', '.join(found_enhancers)}",
                f"Audio enhancement software adds CPU overhead and DPC latency. Disable: {found_enhancers[0]}."
            )
        else:
            results["audio_enhancement_software"] = _ok("No audio enhancement software detected")
    except Exception:
        results["audio_enhancement_software"] = _ok("Could not check audio enhancements")

    # Check audiodg.exe CPU usage
    if PSUTIL_OK:
        try:
            for proc in psutil.process_iter(["name", "cpu_percent"]):
                if (proc.info.get("name") or "").lower() == "audiodg.exe":
                    cpu = proc.info.get("cpu_percent") or 0
                    if cpu > 5:
                        results["audiodg_cpu"] = _warn(
                            f"audiodg.exe at {cpu:.1f}% CPU",
                            "Audio Device Graph is using high CPU. Disable audio enhancements: Sound > Properties > Enhancements > Disable all."
                        )
                    else:
                        results["audiodg_cpu"] = _ok(f"audiodg.exe at {cpu:.1f}% CPU (normal)")
                    break
        except Exception:
            pass

    # Check for multiple audio endpoints via registry
    try:
        try:
            audio_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
            render_keys = list_reg_subkeys(winreg.HKEY_LOCAL_MACHINE, audio_path)
            if len(render_keys) > 3:
                results["audio_endpoints"] = _warn(
                    f"{len(render_keys)} audio render endpoints",
                    "Multiple audio outputs configured. Disable unused audio devices to reduce overhead."
                )
            else:
                results["audio_endpoints"] = _ok(f"{len(render_keys)} audio render endpoint(s)")
        except Exception:
            results["audio_endpoints"] = _ok("Could not enumerate audio endpoints")
    except Exception:
        pass

    return results


# ─── 2.22 Crash & Stability History ─────────────────────────────────────────

def check_crash_stability():
    results = {}

    # Check for recent BSODs via System event log
    def _bsod_check():
        try:
            out = _run([
                "wevtutil", "qe", "System",
                "/q:*[System[Provider[@Name='Microsoft-Windows-WER-SystemErrorReporting'] and EventID=1001]]",
                "/c:5", "/rd:true", "/f:text"
            ], "")
            if out and "Event[" in out:
                return {"recent_bsods": _crit(
                    "BSOD events found in event log",
                    "Blue Screen crashes detected recently. Check dump files and run 'sfc /scannow'. May indicate driver or hardware issues."
                )}
            return {"recent_bsods": _ok("No recent BSOD events")}
        except Exception:
            return {"recent_bsods": _ok("Could not query BSOD history")}

    # Check for game/application crashes
    def _app_crash_check():
        try:
            out = _run([
                "wevtutil", "qe", "Application",
                "/q:*[System[Provider[@Name='Application Error'] and EventID=1000]]",
                "/c:10", "/rd:true", "/f:text"
            ], "")
            if out and "Event[" in out:
                crash_count = out.count("Event[")
                return {"app_crashes": _warn(
                    f"{crash_count} application crash(es) in event log",
                    "Recent application crashes detected. May indicate driver compatibility issues or corrupted game files."
                )}
            return {"app_crashes": _ok("No recent application crashes")}
        except Exception:
            return {"app_crashes": _ok("Could not query application crash history")}

    # Check for crash dump files
    def _dump_check():
        try:
            dump_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps")
            if os.path.isdir(dump_dir):
                dumps = [f for f in os.listdir(dump_dir) if f.endswith(".dmp")]
                if dumps:
                    return {"crash_dump_files": _warn(
                        f"{len(dumps)} crash dump(s) in CrashDumps",
                        f"Crash dumps found in {dump_dir}. Analyze with WinDbg or report to game developers."
                    )}
                return {"crash_dump_files": _ok("No crash dumps found")}
            # Also check Windows minidump
            minidump_dir = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Minidump")
            if os.path.isdir(minidump_dir):
                mdumps = [f for f in os.listdir(minidump_dir) if f.endswith(".dmp")]
                if mdumps:
                    return {"crash_dump_files": _warn(
                        f"{len(mdumps)} minidump(s) in Windows\\Minidump",
                        "Windows minidumps found. These are from BSOD crashes. Analyze with BlueScreenView or WinDbg."
                    )}
            return {"crash_dump_files": _ok("No crash dumps found")}
        except Exception:
            return {"crash_dump_files": _ok("Could not check crash dumps")}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_bsod_check), executor.submit(_app_crash_check), executor.submit(_dump_check)]
        for f in futures:
            results.update(f.result())

    return results


# ─── 2.23 Background Network Activity ───────────────────────────────────────

def _measure_net_throughput():
    """Measure network throughput over 2 seconds. Runs in thread to avoid blocking."""
    try:
        net1 = psutil.net_io_counters()
        time.sleep(2)
        net2 = psutil.net_io_counters()

        bytes_sent = net2.bytes_sent - net1.bytes_sent
        bytes_recv = net2.bytes_recv - net1.bytes_recv
        mbps_up = (bytes_sent * 8) / (2 * 1_000_000)  # 2 sec interval
        mbps_down = (bytes_recv * 8) / (2 * 1_000_000)
        return mbps_down, mbps_up
    except Exception:
        return None, None


def check_background_network():
    results = {}

    if not PSUTIL_OK:
        return {"error": _warn("psutil unavailable", "Install psutil.")}

    try:
        # Measure current network throughput in a thread to avoid blocking main thread
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_measure_net_throughput)
            mbps_down, mbps_up = future.result(timeout=10)

        if mbps_down is not None:
            if mbps_down > 50:
                results["background_bandwidth"] = _warn(
                    f"Down: {mbps_down:.1f} Mbps, Up: {mbps_up:.1f} Mbps",
                    "High background download activity detected. This will cause lag in online games. Check for active downloads."
                )
            elif mbps_down > 10:
                results["background_bandwidth"] = _warn(
                    f"Down: {mbps_down:.1f} Mbps, Up: {mbps_up:.1f} Mbps",
                    "Moderate background network activity. May cause latency spikes in competitive games."
                )
            else:
                results["background_bandwidth"] = _ok(
                    f"Down: {mbps_down:.1f} Mbps, Up: {mbps_up:.1f} Mbps (low)"
                )
        else:
            results["background_bandwidth"] = _ok("Could not measure network throughput")
    except Exception:
        results["background_bandwidth"] = _ok("Could not measure network throughput")

    # Check active established connection count
    try:
        connections = psutil.net_connections(kind='inet')
        total_established = sum(1 for c in connections if c.status == 'ESTABLISHED')

        if total_established > 100:
            results["active_connections"] = _warn(
                f"{total_established} established TCP connections",
                "Very high number of active network connections. Browser tabs and background apps are using bandwidth."
            )
        else:
            results["active_connections"] = _ok(f"{total_established} established TCP connections")
    except Exception:
        results["active_connections"] = _ok("Could not enumerate connections")

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
        "startup_programs": check_startup_programs(),
        "dpc_latency": check_dpc_latency(wmi_client),
        "problematic_services": check_problematic_services(wmi_client),
        "event_log_errors": check_event_log_errors(),
        "deep_driver_analysis": check_deep_driver_analysis(wmi_client),
        "irq_analysis": check_irq_analysis(wmi_client),
        "windows_update_status": check_windows_update_status(wmi_client),
        "virtual_memory_config": check_virtual_memory_config(),
        "audio_subsystem": check_audio_subsystem(),
        "crash_stability": check_crash_stability(),
        "background_network": check_background_network(),
    }

    return diagnosis

