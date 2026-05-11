"""Phase 4: Settings audit — check every relevant performance setting."""

import subprocess
import winreg

from utils.registry import read_reg, read_reg_dword, list_reg_subkeys

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False


def _item(category, setting, current_value, verdict, recommendation):
    return {
        "category": category,
        "setting": setting,
        "current_value": str(current_value),
        "verdict": verdict,
        "recommendation": recommendation,
    }


def _run(cmd, default=""):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip()
    except Exception:
        return default


def audit_power_plan():
    output = _run(["powercfg", "/getactivescheme"], "")
    plan_name = "Unknown"
    plan_guid = ""
    if output:
        if "(" in output and ")" in output:
            plan_name = output[output.index("(") + 1:output.rindex(")")]
        parts = output.split()
        for p in parts:
            if "-" in p and len(p) == 36:
                plan_guid = p.lower()

    HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"

    if plan_guid in (HIGH_PERF, ULTIMATE):
        verdict = "optimal"
        rec = "Power plan is set for maximum performance."
    elif "balanced" in plan_name.lower():
        verdict = "suboptimal"
        rec = "Switch to High Performance: powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    elif "saver" in plan_name.lower():
        verdict = "problematic"
        rec = "Power Saver severely limits performance. Switch to High Performance immediately."
    else:
        verdict = "suboptimal"
        rec = "Verify this plan has processor max state at 100% and GPU set to maximum performance."

    return _item("Power", "Power Plan", plan_name, verdict, rec)


def audit_hags():
    hags = read_reg(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
        "HwSchMode",
        default=None
    )
    if hags == 2:
        return _item("GPU", "Hardware-Accelerated GPU Scheduling", "Enabled", "optimal",
                     "HAGS is enabled. Benefits most systems with modern GPU/driver.")
    elif hags == 1:
        return _item("GPU", "Hardware-Accelerated GPU Scheduling", "Disabled", "suboptimal",
                     "Enable HAGS: Settings > System > Display > Graphics > Change default graphics settings.")
    else:
        return _item("GPU", "Hardware-Accelerated GPU Scheduling", "Unknown", "suboptimal",
                     "Could not determine HAGS status. Check Settings > System > Display > Graphics.")


def audit_game_mode():
    val = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\GameBar",
        "AllowAutoGameMode",
        default=None
    )
    if val == 1:
        return _item("Windows", "Game Mode", "Enabled", "optimal",
                     "Game Mode is enabled. Windows will prioritize game processes.")
    elif val == 0:
        return _item("Windows", "Game Mode", "Disabled", "suboptimal",
                     "Enable Game Mode: Settings > Gaming > Game Mode.")
    else:
        return _item("Windows", "Game Mode", "Unknown", "suboptimal",
                     "Game Mode status unknown. Enable in Settings > Gaming > Game Mode.")


def audit_game_dvr():
    dvr = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
        "AllowGameDVR",
        default=None
    )
    app_captures = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\GameBar",
        "UseNexusForGameBarEnabled",
        default=None
    )
    if dvr == 0:
        return _item("Windows", "Xbox Game DVR / Captures", "Disabled", "optimal",
                     "Game DVR is disabled. No background recording overhead.")
    elif dvr == 1:
        return _item("Windows", "Xbox Game DVR / Captures", "Enabled", "suboptimal",
                     "Disable Game DVR: Xbox app > Settings > Captures, or set AllowGameDVR=0 in registry.")
    else:
        return _item("Windows", "Xbox Game DVR / Captures", "Unknown", "suboptimal",
                     "Check Xbox app > Settings > Captures to disable background recording.")


def audit_visual_effects():
    vfx = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
        "VisualFXSetting",
        default=None
    )
    vfx_map = {0: "Let Windows decide", 1: "Best appearance", 2: "Best performance", 3: "Custom"}
    vfx_str = vfx_map.get(vfx, f"Unknown ({vfx})")

    if vfx == 2:
        return _item("Windows", "Visual Effects", "Best performance", "optimal",
                     "Visual effects optimized for performance.")
    elif vfx == 3:
        return _item("Windows", "Visual Effects", "Custom", "optimal",
                     "Custom visual effects. Verify unnecessary animations are disabled.")
    elif vfx is not None:
        return _item("Windows", "Visual Effects", vfx_str, "suboptimal",
                     "Set to 'Adjust for best performance': System Properties > Advanced > Performance > Settings.")
    else:
        return _item("Windows", "Visual Effects", "Unknown", "suboptimal",
                     "Set visual effects to 'Adjust for best performance' in Advanced System Properties.")


def audit_transparency():
    trans = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "EnableTransparency",
        default=None
    )
    if trans == 0:
        return _item("Windows", "Transparency Effects", "Disabled", "optimal",
                     "Transparency effects are off.")
    elif trans == 1:
        return _item("Windows", "Transparency Effects", "Enabled", "suboptimal",
                     "Disable: Settings > Personalization > Colors > Transparency effects OFF.")
    else:
        return _item("Windows", "Transparency Effects", "Unknown", "suboptimal",
                     "Disable transparency: Settings > Personalization > Colors.")


def audit_animations():
    anim = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"Control Panel\Desktop\WindowMetrics",
        "MinAnimate",
        default=None
    )
    anim_val = str(anim) if anim is not None else "Unknown"
    if str(anim) == "0":
        return _item("Windows", "Window Animations", "Disabled", "optimal",
                     "Window animations are disabled.")
    elif str(anim) == "1":
        return _item("Windows", "Window Animations", "Enabled", "suboptimal",
                     "Disable animations in Visual Effects settings (Custom > uncheck all animations).")
    else:
        return _item("Windows", "Window Animations", anim_val, "suboptimal",
                     "Disable animations via Visual Effects > Custom settings.")


def audit_memory_integrity():
    hvci = read_reg(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
        "Enabled",
        default=None
    )
    if hvci == 1:
        return _item("Security", "Memory Integrity (HVCI)", "Enabled", "suboptimal",
                     "HVCI adds 5-15% overhead. Disable in Windows Security > Device Security > Core isolation if not required.")
    elif hvci == 0:
        return _item("Security", "Memory Integrity (HVCI)", "Disabled", "optimal",
                     "HVCI is disabled. Maximum driver compatibility and performance.")
    else:
        return _item("Security", "Memory Integrity (HVCI)", "Unknown/Default", "optimal",
                     "HVCI state unknown. Check Windows Security > Device Security > Core isolation.")


def audit_sysmain():
    try:
        start_val = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\SysMain",
            "Start",
            default=None
        )
        if start_val == 4:
            return _item("Services", "SysMain (Superfetch)", "Disabled", "optimal",
                         "SysMain is disabled. No background disk preloading.")
        elif start_val in (2, 3):
            return _item("Services", "SysMain (Superfetch)", "Enabled", "suboptimal",
                         "SysMain can cause HDD thrashing. Safe to disable on SSD-only systems via services.msc.")
        else:
            return _item("Services", "SysMain (Superfetch)", f"Start={start_val}", "suboptimal",
                         "Check SysMain service status in services.msc.")
    except Exception:
        return _item("Services", "SysMain (Superfetch)", "Unknown", "suboptimal",
                     "Could not read SysMain service state.")


def audit_windows_search():
    try:
        start_val = read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\WSearch",
            "Start",
            default=None
        )
        if start_val == 4:
            return _item("Services", "Windows Search Indexing", "Disabled", "optimal",
                         "Search indexing is disabled. Reduces background disk I/O.")
        elif start_val in (2, 3):
            return _item("Services", "Windows Search Indexing", "Enabled", "suboptimal",
                         "Search indexing causes background disk I/O. Disable if you use Everything or don't use Windows Search.")
        else:
            return _item("Services", "Windows Search Indexing", f"Start={start_val}", "suboptimal",
                         "Check Windows Search service in services.msc.")
    except Exception:
        return _item("Services", "Windows Search Indexing", "Unknown", "suboptimal",
                     "Could not read Windows Search service state.")


def audit_processor_max_state():
    output = _run(["powercfg", "/query", "SCHEME_CURRENT",
                   "54533251-82be-4824-96c1-47b60b740d00",
                   "bc5038f7-23e0-4960-96da-33abaf5935ec"], "")
    if "0x00000064" in output:
        return _item("Power", "Processor Max State", "100%", "optimal",
                     "CPU is allowed to run at full speed.")
    elif output:
        # Try to extract the value
        for line in output.split("\n"):
            if "Current AC Power Setting Index" in line or "Current DC Power Setting Index" in line:
                try:
                    val = int(line.split(":")[-1].strip(), 16)
                    if val < 100:
                        return _item("Power", "Processor Max State", f"{val}%", "problematic",
                                     f"Processor max state is {val}%. Set to 100% in Power Options > Processor Power Management.")
                except Exception:
                    pass
        return _item("Power", "Processor Max State", "Could not parse", "suboptimal",
                     "Verify processor max state is 100% in Power Options.")
    else:
        return _item("Power", "Processor Max State", "Unknown", "suboptimal",
                     "Verify processor max state is 100% in Power Options > Processor Power Management.")


def audit_nagle():
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
            return _item("Network", "Nagle's Algorithm", "Disabled", "optimal",
                         "Nagle's algorithm is disabled. Lower network latency for gaming.")
        else:
            return _item("Network", "Nagle's Algorithm", "Enabled (default)", "suboptimal",
                         "Disable Nagle's for lower gaming latency: Set TcpAckFrequency=1 and TCPNoDelay=1 per adapter in registry.")
    except Exception:
        return _item("Network", "Nagle's Algorithm", "Unknown", "suboptimal",
                     "Could not determine Nagle's algorithm status.")


def audit_network_throttling():
    nti = read_reg(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
        "NetworkThrottlingIndex",
        default=None
    )
    if nti is None:
        return _item("Network", "Network Throttling Index", "Default (10)", "suboptimal",
                     "Set to 0xffffffff to disable throttling for gaming: HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile > NetworkThrottlingIndex = FFFFFFFF")
    elif nti == 0xFFFFFFFF or nti == -1:
        return _item("Network", "Network Throttling Index", "Disabled (FFFFFFFF)", "optimal",
                     "Network throttling is disabled.")
    else:
        return _item("Network", "Network Throttling Index", hex(nti), "suboptimal",
                     "Set NetworkThrottlingIndex to 0xffffffff for gaming. Default of 10 limits packets/sec.")


def audit_pagefile_location():
    try:
        if not PSUTIL_OK:
            return _item("Storage", "Pagefile Location", "psutil unavailable", "suboptimal",
                         "Install psutil to check pagefile location.")

        # Check if pagefile exists and which drive
        pagefile_info = _run(["wmic", "pagefile", "list", "brief"], "")
        if pagefile_info:
            if "C:\\" in pagefile_info or "c:\\" in pagefile_info:
                # Check if C: is SSD
                return _item("Storage", "Pagefile Location", "C:\\ (check drive type)", "optimal",
                             "Pagefile is on system drive. Ensure it's an SSD for best performance.")
            else:
                return _item("Storage", "Pagefile Location", pagefile_info[:50], "suboptimal",
                             "Pagefile may be on a slow drive. Move to fastest SSD for best performance.")
        else:
            return _item("Storage", "Pagefile Location", "Unknown", "suboptimal",
                         "Could not determine pagefile location.")
    except Exception:
        return _item("Storage", "Pagefile Location", "Error", "suboptimal",
                     "Could not check pagefile location.")


def audit_usb_selective_suspend():
    output = _run(["powercfg", "/query", "SCHEME_CURRENT",
                   "2a737441-1930-4402-8d77-b2bebba308a3",
                   "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"], "")
    if "0x00000000" in output:
        return _item("Power", "USB Selective Suspend", "Disabled", "optimal",
                     "USB suspend is disabled. Prevents input device disconnects during gaming.")
    elif "0x00000001" in output:
        return _item("Power", "USB Selective Suspend", "Enabled", "suboptimal",
                     "Disable USB selective suspend in Power Options > USB Settings > USB selective suspend setting.")
    else:
        return _item("Power", "USB Selective Suspend", "Unknown/Default", "suboptimal",
                     "Check USB selective suspend in Power Options > Change plan settings > Change advanced power settings > USB Settings.")


def audit_fullscreen_optimizations():
    fse = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"System\GameConfigStore",
        "GameDVR_FSEBehaviorMode",
        default=None
    )
    fse_disabled = read_reg(
        winreg.HKEY_CURRENT_USER,
        r"System\GameConfigStore",
        "GameDVR_DXGIHonorFSEWindowsCompatible",
        default=None
    )
    if fse == 2:
        return _item("Windows", "Fullscreen Optimizations", "FSE Preferred", "optimal",
                     "Fullscreen Exclusive is preferred. Best latency for competitive gaming.")
    elif fse == 0:
        return _item("Windows", "Fullscreen Optimizations", "Enabled (default)", "suboptimal",
                     "Windows may convert fullscreen exclusive to borderless windowed. Disable per-game via executable Properties > Compatibility.")
    else:
        return _item("Windows", "Fullscreen Optimizations", "Default", "suboptimal",
                     "Disable fullscreen optimizations per-game for lower latency: right-click .exe > Properties > Compatibility.")


def audit_notifications():
    try:
        focus = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\default$windows.data.notifications.quiethourssettings\windows.data.notifications.quiethourssettings",
            "Data",
            default=None
        )
        # Simpler approach: check Do Not Disturb / Focus Assist
        qa_val = read_reg(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Notifications\Settings",
            "NOC_GLOBAL_SETTING_ALLOW_TOASTS_ABOVE_LOCK",
            default=None
        )
        return _item("Windows", "Focus Assist / Notifications", "Check manually", "suboptimal",
                     "Enable Focus Assist while gaming: Settings > System > Focus Assist > When I'm playing a game.")
    except Exception:
        return _item("Windows", "Focus Assist / Notifications", "Unknown", "suboptimal",
                     "Enable Focus Assist while gaming: Settings > System > Focus Assist.")


def run_settings_audit():
    """Phase 4 — audit every relevant setting. Returns list of audit items."""
    audit_items = []

    audit_items.append(audit_power_plan())
    audit_items.append(audit_hags())
    audit_items.append(audit_game_mode())
    audit_items.append(audit_game_dvr())
    audit_items.append(audit_visual_effects())
    audit_items.append(audit_transparency())
    audit_items.append(audit_animations())
    audit_items.append(audit_memory_integrity())
    audit_items.append(audit_sysmain())
    audit_items.append(audit_windows_search())
    audit_items.append(audit_processor_max_state())
    audit_items.append(audit_nagle())
    audit_items.append(audit_network_throttling())
    audit_items.append(audit_pagefile_location())
    audit_items.append(audit_usb_selective_suspend())
    audit_items.append(audit_fullscreen_optimizations())
    audit_items.append(audit_notifications())

    return audit_items
