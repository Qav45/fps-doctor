"""Phase 1: Collect full system specifications."""

import subprocess
import platform
import socket
import re
import datetime

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

from utils.wmi_helpers import get_wmi_client, wmi_query


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _run(cmd, default="N/A"):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip()
    except Exception:
        return default


def collect_cpu(wmi_client):
    info = {
        "name": "N/A",
        "cores": "N/A",
        "threads": "N/A",
        "base_clock_mhz": "N/A",
        "boost_clock_mhz": "N/A",
        "architecture": platform.machine(),
        "l2_cache_kb": "N/A",
        "l3_cache_kb": "N/A",
        "microcode": "N/A",
        "stepping": "N/A",
        "socket": "N/A",
    }
    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_Processor",
        ["Name", "NumberOfCores", "NumberOfLogicalProcessors",
         "MaxClockSpeed", "CurrentClockSpeed",
         "L2CacheSize", "L3CacheSize",
         "Description", "Stepping", "SocketDesignation"]
    )
    if rows:
        r = rows[0]
        info["name"] = r.get("Name") or "N/A"
        info["cores"] = r.get("NumberOfCores") or "N/A"
        info["threads"] = r.get("NumberOfLogicalProcessors") or "N/A"
        info["base_clock_mhz"] = r.get("MaxClockSpeed") or "N/A"
        info["boost_clock_mhz"] = r.get("CurrentClockSpeed") or "N/A"
        info["l2_cache_kb"] = r.get("L2CacheSize") or "N/A"
        info["l3_cache_kb"] = r.get("L3CacheSize") or "N/A"
        info["stepping"] = r.get("Stepping") or "N/A"
        info["socket"] = r.get("SocketDesignation") or "N/A"
        desc = r.get("Description") or ""
        # Try to extract microcode from description
        info["microcode"] = desc if desc else "N/A"

    if PSUTIL_OK:
        freq = _safe(lambda: psutil.cpu_freq())
        if freq:
            info["boost_clock_mhz"] = round(freq.max, 1) if freq.max else info["boost_clock_mhz"]
            info["base_clock_mhz"] = round(freq.current, 1) if freq.current else info["base_clock_mhz"]

    return info


def collect_gpu(wmi_client):
    gpus = []
    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_VideoController",
        ["Name", "AdapterRAM", "DriverVersion", "DriverDate",
         "VideoModeDescription", "CurrentRefreshRate",
         "AdapterDACType", "VideoProcessor"]
    )
    gputil_gpus = []
    if GPUTIL_OK:
        try:
            gputil_gpus = GPUtil.getGPUs()
        except Exception:
            gputil_gpus = []

    for i, r in enumerate(rows):
        gpu = {
            "name": r.get("Name") or "N/A",
            "vram_mb": "N/A",
            "driver_version": r.get("DriverVersion") or "N/A",
            "driver_date": "N/A",
            "core_clock_mhz": "N/A",
            "memory_clock_mhz": "N/A",
            "pcie_generation": "N/A",
            "pcie_lanes": "N/A",
            "current_resolution": r.get("VideoModeDescription") or "N/A",
            "refresh_rate": r.get("CurrentRefreshRate") or "N/A",
        }
        # AdapterRAM is uint32 in WMI — overflows at 4 GB. Values near 0xFFFFFFFF are bogus.
        try:
            ram_bytes = int(r.get("AdapterRAM") or 0)
            _UINT32_MAX = 4294967295
            if 0 < ram_bytes < _UINT32_MAX - (1024 * 1024):
                gpu["vram_mb"] = ram_bytes // (1024 * 1024)
        except Exception:
            pass
        # Parse driver date from WMI format (20230101000000.000000+000)
        try:
            dd = r.get("DriverDate") or ""
            if len(dd) >= 8:
                gpu["driver_date"] = f"{dd[0:4]}-{dd[4:6]}-{dd[6:8]}"
        except Exception:
            pass
        # Fill from GPUtil if available
        if i < len(gputil_gpus):
            g = gputil_gpus[i]
            if gpu["vram_mb"] == "N/A":
                gpu["vram_mb"] = int(g.memoryTotal) if g.memoryTotal else "N/A"
        gpus.append(gpu)

    if not gpus:
        gpus.append({"name": "N/A", "vram_mb": "N/A", "driver_version": "N/A",
                     "driver_date": "N/A", "core_clock_mhz": "N/A",
                     "memory_clock_mhz": "N/A", "pcie_generation": "N/A", "pcie_lanes": "N/A"})
    return gpus


def collect_ram(wmi_client):
    info = {
        "total_gb": "N/A",
        "speed_mhz": "N/A",
        "type": "N/A",
        "channels": "N/A",
        "slots_used": "N/A",
        "total_slots": "N/A",
        "cas_latency": "N/A",
    }

    if PSUTIL_OK:
        try:
            vm = psutil.virtual_memory()
            info["total_gb"] = round(vm.total / (1024 ** 3), 1)
        except Exception:
            pass

    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_PhysicalMemory",
        ["Speed", "MemoryType", "SMBIOSMemoryType", "Capacity",
         "FormFactor", "DataWidth", "TotalWidth", "ConfiguredClockSpeed"]
    )

    if rows:
        info["slots_used"] = len(rows)
        speeds = []
        for r in rows:
            spd = r.get("ConfiguredClockSpeed") or r.get("Speed") or 0
            if spd:
                speeds.append(int(spd))
        if speeds:
            info["speed_mhz"] = max(speeds)

        # Detect RAM type from SMBIOSMemoryType
        mem_type_map = {
            26: "DDR4", 34: "DDR5", 24: "DDR3", 22: "DDR2",
            21: "DDR", 20: "SDRAM"
        }
        first_type = rows[0].get("SMBIOSMemoryType") or rows[0].get("MemoryType") or 0
        try:
            info["type"] = mem_type_map.get(int(first_type), f"Type#{first_type}")
        except Exception:
            pass

        # Rough dual-channel detection: if 2 or 4 sticks and total is even distribution
        if len(rows) in (2, 4):
            info["channels"] = "Dual (likely)"
        elif len(rows) == 1:
            info["channels"] = "Single"
        elif len(rows) == 3:
            info["channels"] = "Triple or mixed"
        else:
            info["channels"] = "Unknown"

    # Count physical memory array for total slots
    array_rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_PhysicalMemoryArray",
        ["MemoryDevices"]
    )
    if array_rows:
        try:
            info["total_slots"] = int(array_rows[0].get("MemoryDevices") or 0)
        except Exception:
            pass

    return info


def collect_storage(wmi_client):
    drives = []
    disk_rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_DiskDrive",
        ["DeviceID", "Model", "MediaType", "Size", "FirmwareRevision",
         "InterfaceType", "Status", "Partitions", "SerialNumber"]
    )

    disk_usage = {}
    if PSUTIL_OK:
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disk_usage[part.device.replace("\\", "").upper()] = {
                        "total_gb": round(usage.total / (1024 ** 3), 1),
                        "free_gb": round(usage.free / (1024 ** 3), 1),
                        "mountpoint": part.mountpoint,
                    }
                except Exception:
                    pass
        except Exception:
            pass

    for r in disk_rows:
        model = r.get("Model") or "Unknown"
        media = r.get("MediaType") or ""
        interface = r.get("InterfaceType") or ""
        size_bytes = 0
        try:
            size_bytes = int(r.get("Size") or 0)
        except Exception:
            pass

        # Determine drive type
        if "NVMe" in model or "NVM" in interface or "NVMe" in media:
            dtype = "NVMe"
        elif "SSD" in model or "Solid" in media:
            dtype = "SSD"
        elif "HDD" in media or "Fixed" in media or "External" in media:
            dtype = "HDD"
        else:
            dtype = "Unknown"

        drive = {
            "device_id": r.get("DeviceID") or "N/A",
            "model": model,
            "type": dtype,
            "size_gb": round(size_bytes / (1024 ** 3), 1) if size_bytes else "N/A",
            "free_gb": "N/A",
            "health_status": r.get("Status") or "N/A",
            "firmware": r.get("FirmwareRevision") or "N/A",
            "interface": interface,
            "read_speed_mbps": "N/A",
        }

        # Match this physical disk to its logical partitions via WMI ASSOCIATORS
        try:
            m = re.search(r'(\d+)$', drive["device_id"])
            if m:
                disk_idx = int(m.group(1))
                part_rows = wmi_query(
                    wmi_client,
                    f"SELECT DeviceID FROM Win32_DiskPartition WHERE DiskIndex={disk_idx}",
                    ["DeviceID"]
                )
                for pr in part_rows:
                    part_dev = (pr.get("DeviceID") or "").replace("'", "")
                    ld_rows = wmi_query(
                        wmi_client,
                        f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{part_dev}'}} WHERE ResultClass=Win32_LogicalDisk",
                        ["DeviceID"]
                    )
                    for lr in ld_rows:
                        ld_id = (lr.get("DeviceID") or "").rstrip("\\").upper()
                        if ld_id in disk_usage:
                            drive["free_gb"] = disk_usage[ld_id]["free_gb"]
                            break
                    if drive["free_gb"] != "N/A":
                        break
        except Exception:
            pass

        drives.append(drive)

    if not drives:
        # Fallback: use psutil
        if PSUTIL_OK:
            try:
                for part in psutil.disk_partitions(all=False):
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        drives.append({
                            "device_id": part.device,
                            "model": "Unknown",
                            "type": "Unknown",
                            "size_gb": round(usage.total / (1024 ** 3), 1),
                            "free_gb": round(usage.free / (1024 ** 3), 1),
                            "health_status": "N/A",
                            "firmware": "N/A",
                            "interface": part.fstype,
                            "read_speed_mbps": "N/A",
                        })
                    except Exception:
                        pass
            except Exception:
                pass

    return drives


def collect_motherboard(wmi_client):
    info = {
        "manufacturer": "N/A",
        "model": "N/A",
        "chipset": "N/A",
        "bios_version": "N/A",
        "bios_date": "N/A",
    }
    board_rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_BaseBoard",
        ["Manufacturer", "Product", "Version"]
    )
    if board_rows:
        r = board_rows[0]
        info["manufacturer"] = r.get("Manufacturer") or "N/A"
        info["model"] = r.get("Product") or "N/A"

    bios_rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_BIOS",
        ["Name", "Version", "ReleaseDate", "Manufacturer"]
    )
    if bios_rows:
        r = bios_rows[0]
        info["bios_version"] = r.get("Version") or r.get("Name") or "N/A"
        try:
            rd = r.get("ReleaseDate") or ""
            if len(rd) >= 8:
                info["bios_date"] = f"{rd[0:4]}-{rd[4:6]}-{rd[6:8]}"
        except Exception:
            pass

    return info


def collect_os(wmi_client):
    info = {
        "version": platform.version(),
        "build_number": "N/A",
        "edition": "N/A",
        "install_date": "N/A",
        "uptime_hours": "N/A",
        "last_update": "N/A",
    }
    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_OperatingSystem",
        ["Caption", "BuildNumber", "InstallDate", "LastBootUpTime",
         "OSArchitecture", "Version"]
    )
    if rows:
        r = rows[0]
        info["edition"] = r.get("Caption") or "N/A"
        info["build_number"] = r.get("BuildNumber") or "N/A"
        try:
            idate = r.get("InstallDate") or ""
            if len(idate) >= 8:
                info["install_date"] = f"{idate[0:4]}-{idate[4:6]}-{idate[6:8]}"
        except Exception:
            pass
        try:
            lboot = r.get("LastBootUpTime") or ""
            if len(lboot) >= 14:
                boot_dt = datetime.datetime(
                    int(lboot[0:4]), int(lboot[4:6]), int(lboot[6:8]),
                    int(lboot[8:10]), int(lboot[10:12]), int(lboot[12:14])
                )
                delta = datetime.datetime.now() - boot_dt
                info["uptime_hours"] = round(delta.total_seconds() / 3600, 1)
        except Exception:
            pass

    if PSUTIL_OK:
        try:
            boot_time = psutil.boot_time()
            uptime_s = datetime.datetime.now().timestamp() - boot_time
            info["uptime_hours"] = round(uptime_s / 3600, 1)
        except Exception:
            pass

    return info


def collect_display(wmi_client):
    monitors = []
    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_DesktopMonitor",
        ["Name", "ScreenWidth", "ScreenHeight", "MonitorType"]
    )
    for r in rows:
        monitors.append({
            "name": r.get("Name") or r.get("MonitorType") or "Unknown Monitor",
            "resolution": f"{r.get('ScreenWidth') or '?'}x{r.get('ScreenHeight') or '?'}",
            "refresh_rate": "N/A",
            "connection": "N/A",
        })

    # Try EnumDisplaySettings via ctypes for refresh rate
    try:
        import ctypes
        import ctypes.wintypes

        ENUM_CURRENT_SETTINGS = -1

        class DEVMODE(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", ctypes.c_wchar * 32),
                ("dmSpecVersion", ctypes.c_ushort),
                ("dmDriverVersion", ctypes.c_ushort),
                ("dmSize", ctypes.c_ushort),
                ("dmDriverExtra", ctypes.c_ushort),
                ("dmFields", ctypes.c_ulong),
                ("dmPositionX", ctypes.c_long),
                ("dmPositionY", ctypes.c_long),
                ("dmDisplayOrientation", ctypes.c_ulong),
                ("dmDisplayFixedOutput", ctypes.c_ulong),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", ctypes.c_ushort),
                ("dmBitsPerPel", ctypes.c_ulong),
                ("dmPelsWidth", ctypes.c_ulong),
                ("dmPelsHeight", ctypes.c_ulong),
                ("dmDisplayFlags", ctypes.c_ulong),
                ("dmDisplayFrequency", ctypes.c_ulong),
                ("dmICMMethod", ctypes.c_ulong),
                ("dmICMIntent", ctypes.c_ulong),
                ("dmMediaType", ctypes.c_ulong),
                ("dmDitherType", ctypes.c_ulong),
                ("dmReserved1", ctypes.c_ulong),
                ("dmReserved2", ctypes.c_ulong),
                ("dmPanningWidth", ctypes.c_ulong),
                ("dmPanningHeight", ctypes.c_ulong),
            ]

        dm = DEVMODE()
        dm.dmSize = ctypes.sizeof(DEVMODE)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            refresh = dm.dmDisplayFrequency
            width = dm.dmPelsWidth
            height = dm.dmPelsHeight
            if monitors:
                monitors[0]["refresh_rate"] = f"{refresh}Hz"
                monitors[0]["resolution"] = f"{width}x{height}"
            else:
                monitors.append({
                    "name": "Primary Display",
                    "resolution": f"{width}x{height}",
                    "refresh_rate": f"{refresh}Hz",
                    "connection": "N/A",
                })
    except Exception:
        pass

    if not monitors:
        monitors.append({
            "name": "Unknown",
            "resolution": "N/A",
            "refresh_rate": "N/A",
            "connection": "N/A",
        })

    return monitors


def collect_network(wmi_client):
    adapters = []
    rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_NetworkAdapter WHERE NetConnectionStatus=2",
        ["Name", "Speed", "AdapterType", "MACAddress", "NetConnectionID"]
    )
    for r in rows:
        speed = r.get("Speed")
        try:
            speed_mbps = int(speed) // 1_000_000 if speed else "N/A"
        except Exception:
            speed_mbps = "N/A"
        adapters.append({
            "name": r.get("Name") or "Unknown",
            "speed_mbps": speed_mbps,
            "type": r.get("AdapterType") or "N/A",
            "connection_id": r.get("NetConnectionID") or "N/A",
        })

    if not adapters and PSUTIL_OK:
        try:
            net_if = psutil.net_if_stats()
            for name, stats in net_if.items():
                if stats.isup:
                    adapters.append({
                        "name": name,
                        "speed_mbps": stats.speed if stats.speed else "N/A",
                        "type": "N/A",
                        "connection_id": name,
                    })
        except Exception:
            pass

    return adapters


def collect_power(wmi_client):
    info = {
        "power_plan_name": "N/A",
        "power_plan_guid": "N/A",
        "is_laptop": False,
    }

    # Check for battery (laptop detection)
    if PSUTIL_OK:
        try:
            battery = psutil.sensors_battery()
            info["is_laptop"] = battery is not None
        except Exception:
            pass

    # Get power plan via powercfg
    output = _run(["powercfg", "/getactivescheme"], "")
    if output:
        parts = output.split()
        for i, p in enumerate(parts):
            if "-" in p and len(p) == 36:
                info["power_plan_guid"] = p
                if i + 1 < len(parts):
                    name_parts = parts[i + 1:]
                    # Extract name from parentheses
                    full = " ".join(name_parts)
                    if "(" in full and ")" in full:
                        info["power_plan_name"] = full[full.index("(") + 1:full.rindex(")")]
                    else:
                        info["power_plan_name"] = full
                break

    return info


def collect_peripherals(wmi_client):
    info = {
        "usb_device_count": 0,
        "audio_devices": [],
    }

    usb_rows = wmi_query(
        wmi_client,
        "SELECT Name FROM Win32_USBHub",
        ["Name"]
    )
    info["usb_device_count"] = len(usb_rows)

    audio_rows = wmi_query(
        wmi_client,
        "SELECT * FROM Win32_SoundDevice",
        ["Name", "Status"]
    )
    for r in audio_rows:
        info["audio_devices"].append({
            "name": r.get("Name") or "Unknown",
            "status": r.get("Status") or "N/A",
        })

    return info


def collect_system_specs():
    """Phase 1 — collect full system specs. Returns a dict."""
    wmi_client = get_wmi_client()

    specs = {
        "cpu": collect_cpu(wmi_client),
        "gpu": collect_gpu(wmi_client),
        "ram": collect_ram(wmi_client),
        "storage": collect_storage(wmi_client),
        "motherboard": collect_motherboard(wmi_client),
        "os": collect_os(wmi_client),
        "display": collect_display(wmi_client),
        "network": collect_network(wmi_client),
        "power": collect_power(wmi_client),
        "peripherals": collect_peripherals(wmi_client),
        "hostname": _safe(socket.gethostname, "N/A"),
    }

    return specs
