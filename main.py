"""FPS Doctor — Windows PC Performance Diagnostic Tool."""

import argparse
import ctypes
import datetime
import os
import sys

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.text import Text
    from rich import box
    RICH_OK = True
except ImportError:
    RICH_OK = False
    # Minimal fallback console
    class Console:
        def print(self, *args, **kwargs):
            text = " ".join(str(a) for a in args)
            # Strip rich markup
            import re
            text = re.sub(r'\[.*?\]', '', text)
            print(text)
        def rule(self, *args, **kwargs):
            print("=" * 60)


BANNER = r"""
  _______ _____   _____    _____             _
 |  ____||  __ \ / ____|  |  __ \           | |
 | |__   | |__) | (___    | |  | | ___   ___| |_ ___  _ __
 |  __|  |  ___/ \___ \   | |  | |/ _ \ / __| __/ _ \| '__|
 | |     | |     ____) |  | |__| | (_) | (__| || (_) | |
 |_|     |_|    |_____/   |_____/ \___/ \___|\__\___/|_|
"""

VERSION = "1.0.0"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def print_banner(console):
    if RICH_OK:
        console.print(Panel(
            f"[bold cyan]{BANNER}[/bold cyan]\n"
            f"[white]  v{VERSION}  |  Windows PC Performance Diagnostic Tool[/white]\n"
            f"[dim]  Diagnoses FPS drops, bottlenecks, and settings issues[/dim]",
            border_style="bright_blue",
            expand=False,
        ))
    else:
        console.print(BANNER)
        console.print(f"FPS Doctor v{VERSION} — Windows PC Performance Diagnostic Tool")
        console.print("=" * 60)


def print_phase(console, number, name, status="running"):
    if RICH_OK:
        icons = {"running": "[yellow]>>>[/yellow]", "done": "[green]OK [/green]", "skip": "[dim]---[/dim]"}
        icon = icons.get(status, ">>>")
        console.print(f"  {icon} Phase {number}: {name}")
    else:
        console.print(f"  [{status.upper()}] Phase {number}: {name}")


def run_phase_with_spinner(console, description, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) while showing a spinner. Returns the result."""
    if RICH_OK:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(description, total=None)
            result = fn(*args, **kwargs)
            progress.update(task, completed=True)
        return result
    else:
        console.print(f"  Running: {description}")
        return fn(*args, **kwargs)


def print_critical_summary(console, diagnosis, bottlenecks, settings_audit):
    """Print a rich summary table of the most critical findings."""
    if not RICH_OK:
        console.print("\n--- CRITICAL FINDINGS SUMMARY ---")
        critical_items = []

        for section_key, section_data in diagnosis.items():
            if not isinstance(section_data, dict):
                continue
            for check_name, check_data in section_data.items():
                if not isinstance(check_data, dict):
                    continue
                if check_data.get("status") in ("critical", "warning"):
                    critical_items.append({
                        "source": check_name,
                        "status": check_data.get("status"),
                        "value": check_data.get("value", ""),
                        "rec": check_data.get("recommendation", ""),
                    })

        for item in critical_items[:10]:
            console.print(f"  [{item['status'].upper()}] {item['source']}: {item['rec'][:60]}")

        for b in bottlenecks:
            if b.get("severity") == "high":
                console.print(f"  [BOTTLENECK-HIGH] {b.get('type')}: {b.get('recommendation', '')[:60]}")
        return

    # Rich version
    console.print()
    console.rule("[bold yellow]CRITICAL FINDINGS SUMMARY[/bold yellow]")

    table = Table(
        show_header=True,
        header_style="bold white on dark_blue",
        box=box.ROUNDED,
        expand=True,
        show_lines=True,
    )
    table.add_column("Source", style="cyan", min_width=22, max_width=28)
    table.add_column("Status", style="bold", min_width=10, max_width=12)
    table.add_column("Value", style="white", min_width=18, max_width=25)
    table.add_column("Recommendation", style="yellow", min_width=30, ratio=1)

    has_rows = False

    # Critical diagnosis items
    for section_key, section_data in diagnosis.items():
        if not isinstance(section_data, dict):
            continue
        for check_name, check_data in section_data.items():
            if not isinstance(check_data, dict):
                continue
            status = check_data.get("status", "ok")
            if status == "critical":
                label = Text("CRITICAL", style="bold red")
                table.add_row(
                    check_name.replace("_", " ").title()[:28],
                    label,
                    str(check_data.get("value", ""))[:25],
                    str(check_data.get("recommendation", ""))[:120],
                )
                has_rows = True

    # High-severity warnings
    for section_key, section_data in diagnosis.items():
        if not isinstance(section_data, dict):
            continue
        for check_name, check_data in section_data.items():
            if not isinstance(check_data, dict):
                continue
            status = check_data.get("status", "ok")
            if status == "warning":
                label = Text("WARNING", style="bold yellow")
                table.add_row(
                    check_name.replace("_", " ").title()[:28],
                    label,
                    str(check_data.get("value", ""))[:25],
                    str(check_data.get("recommendation", ""))[:120],
                )
                has_rows = True

    # High-severity bottlenecks
    for b in bottlenecks:
        severity = b.get("severity", "low")
        if severity in ("high", "medium"):
            color = "bold red" if severity == "high" else "bold yellow"
            label = Text(f"BOTTLENECK\n({severity.upper()})", style=color)
            table.add_row(
                b.get("type", "")[:28],
                label,
                "",
                str(b.get("recommendation", ""))[:120],
            )
            has_rows = True

    # Problematic settings
    for item in settings_audit:
        if item.get("verdict") == "problematic":
            label = Text("PROBLEMATIC", style="bold red")
            table.add_row(
                item.get("setting", "")[:28],
                label,
                str(item.get("current_value", ""))[:25],
                str(item.get("recommendation", ""))[:120],
            )
            has_rows = True

    if has_rows:
        console.print(table)
    else:
        console.print("[green]  No critical issues found! Your system appears well configured.[/green]")

    # Summary counts
    total_critical = sum(
        1 for s in diagnosis.values() if isinstance(s, dict)
        for c in s.values() if isinstance(c, dict) and c.get("status") == "critical"
    )
    total_warning = sum(
        1 for s in diagnosis.values() if isinstance(s, dict)
        for c in s.values() if isinstance(c, dict) and c.get("status") == "warning"
    )
    total_bottlenecks = len(bottlenecks)
    total_suboptimal = sum(1 for item in settings_audit if item.get("verdict") != "optimal")

    console.print()
    if RICH_OK:
        summary_table = Table.grid(padding=(0, 4))
        summary_table.add_column(style="bold")
        summary_table.add_column()
        summary_table.add_row(
            "[red]Critical Issues:[/red]", str(total_critical),
        )
        summary_table.add_row(
            "[yellow]Warnings:[/yellow]", str(total_warning),
        )
        summary_table.add_row(
            "[orange3]Bottlenecks:[/orange3]", str(total_bottlenecks),
        )
        summary_table.add_row(
            "[cyan]Suboptimal Settings:[/cyan]", str(total_suboptimal),
        )
        console.print(Panel(summary_table, title="[bold]Issue Count", border_style="dim"))
    else:
        console.print(f"  Critical: {total_critical}  Warnings: {total_warning}  Bottlenecks: {total_bottlenecks}  Suboptimal: {total_suboptimal}")


def get_monitoring_duration(args, console):
    """Return monitoring duration in seconds from args or interactive prompt."""
    if args.duration is not None:
        return int(args.duration * 60)

    if RICH_OK:
        console.print()
        console.print(Panel(
            "[bold]Phase 5: Live Performance Monitoring[/bold]\n\n"
            "FPS Doctor will now monitor your system live.\n"
            "Run a game or benchmark during this period for best results.\n\n"
            "[dim]Default: 10 minutes | Enter 0 to skip[/dim]",
            border_style="cyan",
        ))
    else:
        console.print("\nPhase 5: Live Performance Monitoring")
        console.print("Run a game or benchmark during monitoring for best results.")
        console.print("Enter 0 to skip.")

    try:
        user_input = input("  Enter monitoring duration in minutes [default: 10]: ").strip()
        if not user_input:
            return 600  # 10 minutes default
        minutes = float(user_input)
        return int(minutes * 60)
    except (ValueError, EOFError):
        return 600


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"FPS Doctor v{VERSION} — Windows PC Performance Diagnostic Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        metavar="MINUTES",
        help="Monitoring duration in minutes (default: prompt interactively; 0 to skip)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Output report file path (default: fps_doctor_report_TIMESTAMP.txt in current dir)"
    )
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="Skip the live monitoring phase"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    console = Console()

    print_banner(console)

    # Admin check
    if not is_admin():
        if RICH_OK:
            console.print(Panel(
                "[yellow]Warning:[/yellow] Not running as Administrator.\n"
                "Some WMI queries and registry reads may be limited.\n"
                "For best results, run as Administrator.",
                border_style="yellow",
                title="Permissions",
            ))
        else:
            console.print("WARNING: Not running as Administrator. Some data may be unavailable.")
    else:
        if RICH_OK:
            console.print("[green]  Running as Administrator. Full access enabled.[/green]")
        else:
            console.print("  Running as Administrator.")

    console.print()

    # ── Phase 1: System Specs ────────────────────────────────────────────────
    print_phase(console, 1, "Collecting System Specifications")
    try:
        from collectors.system_specs import collect_system_specs
        system_specs = run_phase_with_spinner(
            console, "Querying hardware via WMI...", collect_system_specs
        )
        print_phase(console, 1, "System Specifications", "done")
    except Exception as e:
        console.print(f"  [red]Phase 1 error: {e}[/red]" if RICH_OK else f"  Phase 1 error: {e}")
        system_specs = {}

    # ── Phase 2: FPS Diagnosis ───────────────────────────────────────────────
    print_phase(console, 2, "Running FPS Loss Diagnosis (12 sections)")
    diagnosis = {}
    try:
        from collectors.fps_diagnosis import run_fps_diagnosis

        section_names = [
            "Driver Issues", "Background Processes", "Thermal & Power",
            "Memory Issues", "Storage Issues", "Network Issues",
            "Software Overlays", "Windows Settings", "GPU Settings",
            "DirectX & Runtimes", "BIOS & Firmware", "Display Issues",
        ]

        if RICH_OK:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Running diagnosis...", total=12)
                diagnosis = run_fps_diagnosis(system_specs)
                progress.update(task, completed=12)
        else:
            diagnosis = run_fps_diagnosis(system_specs)

        print_phase(console, 2, "FPS Loss Diagnosis", "done")
    except Exception as e:
        console.print(f"  [red]Phase 2 error: {e}[/red]" if RICH_OK else f"  Phase 2 error: {e}")
        diagnosis = {}

    # ── Phase 3: Bottleneck Analysis ─────────────────────────────────────────
    print_phase(console, 3, "Analyzing Bottlenecks (5-second live sample)")
    bottlenecks = []
    try:
        from collectors.bottleneck import run_bottleneck_analysis
        bottlenecks = run_phase_with_spinner(
            console, "Sampling CPU/GPU/RAM for 5 seconds...",
            run_bottleneck_analysis, system_specs, 5
        )
        print_phase(console, 3, f"Bottleneck Analysis ({len(bottlenecks)} found)", "done")
    except Exception as e:
        console.print(f"  [red]Phase 3 error: {e}[/red]" if RICH_OK else f"  Phase 3 error: {e}")
        bottlenecks = []

    # ── Phase 4: Settings Audit ──────────────────────────────────────────────
    print_phase(console, 4, "Auditing Performance Settings")
    settings_audit = []
    try:
        from collectors.settings_audit import run_settings_audit
        settings_audit = run_phase_with_spinner(
            console, "Checking registry and power settings...", run_settings_audit
        )
        print_phase(console, 4, f"Settings Audit ({len(settings_audit)} settings checked)", "done")
    except Exception as e:
        console.print(f"  [red]Phase 4 error: {e}[/red]" if RICH_OK else f"  Phase 4 error: {e}")
        settings_audit = []

    # ── Phase 5: Live Monitoring ─────────────────────────────────────────────
    monitoring_data = {"samples": [], "stats": {}, "spikes": [], "throttle_events": [], "sample_count": 0}

    skip_monitoring = args.no_monitor

    if not skip_monitoring:
        duration_seconds = get_monitoring_duration(args, console)

        if duration_seconds <= 0:
            print_phase(console, 5, "Live Monitoring (skipped)", "skip")
            skip_monitoring = True
        else:
            print_phase(console, 5, f"Live Monitoring ({duration_seconds}s)")
            try:
                from collectors.monitor import run_monitoring
                monitoring_data = run_monitoring(
                    duration_seconds=duration_seconds,
                    sample_interval=1,
                    console=console,
                )
                print_phase(
                    console, 5,
                    f"Live Monitoring ({monitoring_data.get('sample_count', 0)} samples, "
                    f"{len(monitoring_data.get('spikes', []))} spikes)",
                    "done"
                )
            except KeyboardInterrupt:
                console.print("\n[yellow]  Monitoring interrupted. Continuing to report generation.[/yellow]" if RICH_OK
                              else "\n  Monitoring interrupted. Continuing to report generation.")
                print_phase(console, 5, "Live Monitoring (interrupted)", "skip")
            except Exception as e:
                console.print(f"  [red]Phase 5 error: {e}[/red]" if RICH_OK else f"  Phase 5 error: {e}")
    else:
        print_phase(console, 5, "Live Monitoring (skipped via --no-monitor)", "skip")

    # ── Phase 6: Report Generation ───────────────────────────────────────────
    print_phase(console, 6, "Generating Report")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_path = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, f"fps_doctor_report_{timestamp}.txt")

    try:
        from analyzers.report import generate_report
        final_path = run_phase_with_spinner(
            console, "Writing report...",
            generate_report,
            system_specs, diagnosis, bottlenecks, settings_audit, monitoring_data, output_path
        )
        print_phase(console, 6, "Report Generated", "done")

        if RICH_OK:
            console.print()
            console.print(Panel(
                f"[bold green]Report saved to:[/bold green]\n[white]{final_path}[/white]",
                border_style="green",
                title="[bold]Output",
            ))
        else:
            console.print(f"\n  Report saved to: {final_path}")

    except Exception as e:
        console.print(f"  [red]Phase 6 error: {e}[/red]" if RICH_OK else f"  Phase 6 error: {e}")
        final_path = None

    # ── Summary Table ────────────────────────────────────────────────────────
    try:
        print_critical_summary(console, diagnosis, bottlenecks, settings_audit)
    except Exception as e:
        console.print(f"  Warning: Could not render summary: {e}")

    if RICH_OK:
        console.print()
        console.rule("[dim]FPS Doctor complete[/dim]")
    else:
        console.print("\n=== FPS Doctor complete ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
