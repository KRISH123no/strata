"""`strata scan`, `now`, `since`, `safe`, `install`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .diff import NOISE, attribute, changes
from .model import Snapshot
from .report import (
    BOLD,
    DIM,
    biggest,
    changes_lines,
    coverage_line,
    forecast_line,
    paint,
    short,
    size,
    suggestions,
    volume_lines,
)
from .store import Store, default_path
from .volume import inspect
from .walk import walk

LABEL = "com.strata.nightly"


def take(root: str, *, progress: bool = False) -> Snapshot:
    seen = [0]

    def tick(_folder: str) -> None:
        seen[0] += 1
        if progress and seen[0] % 500 == 0 and sys.stdout.isatty():
            print(f"\r  {seen[0]:,} folders", end="", flush=True)

    walked = walk(root, on_dir=tick)
    if progress and sys.stdout.isatty():
        print("\r" + " " * 30, end="\r")
    volume = inspect("/")
    return Snapshot(
        taken=time.time(), root=os.path.abspath(os.path.expanduser(root)),
        entries=walked.sizes, files=walked.files, total=walked.total,
        free=volume.truly_free, capacity=volume.capacity,
    )


def _when(text: str) -> float:
    """"yesterday", "7d", "2026-10-01" — all of them mean a moment."""
    now = datetime.now()
    if text in ("yesterday", "1d"):
        return (now - timedelta(days=1)).timestamp()
    if text.endswith("d") and text[:-1].isdigit():
        return (now - timedelta(days=int(text[:-1]))).timestamp()
    if text.endswith("w") and text[:-1].isdigit():
        return (now - timedelta(weeks=int(text[:-1]))).timestamp()
    try:
        return datetime.strptime(text, "%Y-%m-%d").timestamp()
    except ValueError:
        raise SystemExit(
            f"not a time: {text!r} — try 7d, 2w, yesterday, or 2026-10-01"
        ) from None


# ---------------------------------------------------------------- commands


def cmd_scan(args) -> int:
    store = Store(args.db)
    started = time.perf_counter()
    print(f"scanning {short(args.root, width=40)} …")
    snapshot = take(args.root, progress=True)
    store.save(snapshot)
    print(
        f"  {snapshot.files:,} files, {size(snapshot.total)}, "
        f"{len(snapshot.entries):,} folders worth naming, "
        f"in {time.perf_counter() - started:.1f}s"
    )
    if store.count() == 1:
        print(paint("\n  this is the first scan — run it again tomorrow and "
                    "`strata since yesterday` will have something to say.", DIM))
    return 0


def cmd_demo(args) -> int:
    """Report on a pretend fortnight, so the point is visible with no history."""
    import tempfile

    from .demo import build

    holder = tempfile.TemporaryDirectory()
    args.db = str(Path(holder.name) / "demo.db")
    store = Store(args.db)
    days = build(store)
    print(paint(f"a pretend {days} days of scans\n", DIM))

    args.limit, args.under = 8, None
    print(paint("$ strata now", BOLD))
    cmd_now(args)
    print()
    print(paint("$ strata since 7d", BOLD))
    args.when, args.noise = "7d", NOISE
    cmd_since(args)
    print()
    print(paint("$ strata safe", BOLD))
    cmd_safe(args)
    return 0


def cmd_now(args) -> int:
    store = Store(args.db)
    snapshot = store.latest()
    volume = inspect("/")
    print("\n".join(volume_lines(volume)))
    if snapshot is None:
        print("\n  no scan yet — run `strata scan`")
        return 1
    entries, root = snapshot.entries, snapshot.root
    if args.under:
        under = os.path.abspath(os.path.expanduser(args.under))
        entries = {
            p: b for p, b in entries.items()
            if p == under or p.startswith(under.rstrip("/") + "/")
        }
        root = under
        if not entries:
            print(f"\n  nothing recorded under {short(under)}")
            return 1
        print(paint(f"  inside {short(under)}: {size(entries.get(under, 0))}", DIM))
    else:
        print(coverage_line(snapshot.total, volume))
    print()
    print("\n".join(biggest(entries, limit=args.limit, root=root)))
    snapshots = store.all()
    if len(snapshots) > 1:
        print()
        print(forecast_line(snapshots))
    return 0


def cmd_since(args) -> int:
    store = Store(args.db)
    after = store.latest()
    if after is None:
        print("  no scan yet — run `strata scan`")
        return 1
    before = store.nearest(_when(args.when))
    if before is None or before.id == after.id:
        print("  only one scan so far — there is nothing to compare it with yet")
        return 1

    gap = (after.taken - before.taken) / 86400
    moved = attribute(changes(before, after), noise=args.noise)
    when_before = datetime.fromtimestamp(before.taken).strftime("%-d %b %H:%M")
    when_after = datetime.fromtimestamp(after.taken).strftime("%-d %b %H:%M")

    print(f"{paint(f'{when_before}  →  {when_after}', BOLD)}   ({gap:.1f} days)")
    free_delta = after.free - before.free
    print(f"  free space {size(free_delta, signed=True)}, now {size(after.free)}")
    print()
    print("\n".join(changes_lines(moved, limit=args.limit)))
    print()
    print(forecast_line(store.all()))
    return 0


def cmd_safe(args) -> int:
    store = Store(args.db)
    snapshot = store.latest()
    if snapshot is None:
        print("  no scan yet — run `strata scan`")
        return 1
    print(paint("strata never deletes anything. these are yours to run.", DIM))
    print()
    print("\n".join(suggestions(snapshot.entries, limit=args.limit)))
    return 0


def cmd_history(args) -> int:
    store = Store(args.db)
    rows = list(store.summaries())
    if not rows:
        print("  no scans yet")
        return 1
    widest = max(r["free"] for r in rows) or 1
    for row in rows:
        from .report import bar

        when = datetime.fromtimestamp(row["taken"]).strftime("%Y-%m-%d %H:%M")
        print(f"  {when}  {bar(row['free'] / widest, 24)} {size(row['free']):>9} free")
    return 0


def cmd_doctor(args) -> int:
    volume = inspect("/")
    tick = "✓"
    print(f"{tick} volume            {size(volume.capacity)}, {size(volume.truly_free)} truly free")
    print(f"{tick} df says free      {size(volume.free)}"
          + (f"  ({size(volume.purgeable)} of it purgeable)" if volume.purgeable else ""))
    print(f"{tick} local snapshots   {len(volume.snapshots) or 'none'}")
    store = Store(args.db)
    print(f"{tick} history           {store.count()} scan(s) in {store.path}")
    print()
    print(paint("  nothing here deletes anything, ever. it prints the command "
                "and leaves it to you.", DIM))
    return 0


# ------------------------------------------------------------------ launchd


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def build_plist(*, python: str | None = None, root: str, hour: int = 3) -> str:
    python = python or sys.executable
    log = Path.home() / ".strata" / "nightly.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string><string>strata</string><string>scan</string>
        <string>--root</string><string>{root}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict><key>PYTHONPATH</key><string>{package_root()}</string></dict>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>17</integer></dict>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
    <key>StandardErrorPath</key><string>{log}</string>
    <key>StandardOutPath</key><string>{log}</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)
    except OSError:
        return subprocess.CompletedProcess(args, 127, "", "launchctl not found")


def check_agent_can_start(python: str) -> None:
    try:
        done = subprocess.run(
            [python, "-c", "import strata"], capture_output=True, text=True, cwd="/",
            env={**os.environ, "PYTHONPATH": str(package_root())}, timeout=30, check=False,
        )
    except OSError as error:
        raise RuntimeError(f"cannot run {python}: {error}") from error
    if done.returncode != 0:
        raise RuntimeError(
            f"{python} cannot import strata when started outside the repository.\n"
            f"  install it there first:  {python} -m pip install -e ."
        )


def cmd_install(args) -> int:
    if sys.platform != "darwin":
        print("the nightly scan runs through launchd, which is macOS only")
        return 1
    try:
        check_agent_can_start(sys.executable)
    except RuntimeError as error:
        print(error)
        return 1
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".strata").mkdir(parents=True, exist_ok=True)
    path.write_text(build_plist(root=args.root, hour=args.hour), encoding="utf-8")
    target = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{target}/{LABEL}")
    if _launchctl("bootstrap", target, str(path)).returncode != 0:
        _launchctl("load", "-w", str(path))
    print(f"installed {path}")
    print(f"a scan will run every night at {args.hour:02d}:17")
    return 0


def cmd_uninstall(args) -> int:
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path = plist_path()
    if path.exists():
        path.unlink()
        print("removed")
        return 0
    print("nothing installed")
    return 0


# ------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strata", description="where the disk went, and what is still going"
    )
    parser.add_argument("--version", action="version", version=f"strata {__version__}")
    parser.add_argument("--db", default=str(default_path()))
    sub = parser.add_subparsers(dest="command")

    def root_arg(p):
        p.add_argument("--root", default=str(Path.home()), help="what to scan (default: home)")

    scan = sub.add_parser("scan", help="take a snapshot of where the space is")
    root_arg(scan)
    scan.set_defaults(func=cmd_scan)

    demo = sub.add_parser("demo", help="see what it does, with no history of your own")
    demo.set_defaults(func=cmd_demo, limit=8, under=None, when="7d")

    now = sub.add_parser("now", help="what is big right now")
    now.add_argument("--limit", type=int, default=14)
    now.add_argument("--under", help="drill into one folder instead of the whole scan")
    now.set_defaults(func=cmd_now)

    since = sub.add_parser("since", help="what changed — the reason this exists")
    since.add_argument("when", nargs="?", default="7d", help="7d, 2w, yesterday, 2026-10-01")
    since.add_argument("--limit", type=int, default=14)
    since.add_argument("--noise", type=int, default=NOISE, help="ignore changes under this")
    since.set_defaults(func=cmd_since)

    safe = sub.add_parser("safe", help="what is only cache, with the command to clear it")
    safe.add_argument("--limit", type=int, default=8)
    safe.set_defaults(func=cmd_safe)

    sub.add_parser("history", help="free space over time").set_defaults(func=cmd_history)
    sub.add_parser("doctor", help="what this Mac reports about itself").set_defaults(func=cmd_doctor)

    install = sub.add_parser("install", help="scan every night")
    root_arg(install)
    install.add_argument("--hour", type=int, default=3)
    install.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="stop scanning").set_defaults(func=cmd_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
