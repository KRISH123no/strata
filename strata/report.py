"""Printing it so the answer is visible without doing arithmetic."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .classify import MANAGED, OFF_LIMITS, RECLAIMABLE, classify
from .diff import Attributed, days_remaining
from .model import Snapshot
from .volume import Volume

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, AMBER, RED, BLUE = (
    "\033[38;5;35m", "\033[38;5;214m", "\033[38;5;203m", "\033[38;5;39m",
)
KIND_COLOUR = {RECLAIMABLE: GREEN, MANAGED: AMBER, OFF_LIMITS: BLUE, "yours": RED}


def colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("STRATA_COLOR") == "always":
        return True
    return sys.stdout.isatty()


def paint(text: str, style: str) -> str:
    return f"{style}{text}{RESET}" if colour() else text


def size(count: float, *, signed: bool = False) -> str:
    """Bytes, in the units a person would say out loud."""
    sign = "+" if signed and count > 0 else "-" if count < 0 else ""
    count = abs(count)
    for unit, step in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if count >= step:
            return f"{sign}{count / step:.1f} {unit}"
    return f"{sign}{count:.0f} B"


def short(path: str, *, width: int = 46) -> str:
    text = str(path).replace(str(Path.home()), "~")
    return text if len(text) <= width else "…" + text[-(width - 1):]


def bar(fraction: float, width: int = 28) -> str:
    blocks = " ▏▎▍▌▋▊▉█"
    fraction = max(0.0, min(1.0, fraction))
    eighths = round(fraction * width * 8)
    full, rest = divmod(eighths, 8)
    return ("█" * full + (blocks[rest] if rest else "")).ljust(width)


def volume_lines(volume: Volume) -> list[str]:
    """The headline, including the part `df` does not admit to."""
    used = volume.capacity - volume.truly_free
    out = [
        f"  {paint(bar(used / volume.capacity if volume.capacity else 0), BOLD)}"
        f"  {size(volume.truly_free)} free of {size(volume.capacity)}",
    ]
    if volume.purgeable:
        note = (
            f"{size(volume.purgeable)} of what df calls free is purgeable — "
            "space the system might release, not space you have"
        )
        out.append(f"  {paint(note, DIM)}")
    if volume.snapshots:
        note = (
            f"{len(volume.snapshots)} local snapshot(s) on this volume — "
            "real bytes, invisible to Finder and to du"
        )
        out.append(f"  {paint(note, DIM)}")
    return out


def biggest(entries: dict[str, int], *, limit: int = 14, root: str = "") -> list[str]:
    """What is large now, with what each thing actually is."""
    from .walk import highlights

    items = highlights(entries, root=root, limit=limit)
    if not items:
        return ["  nothing recorded"]
    widest = items[0][1] or 1
    out = []
    for path, count in items:
        verdict = classify(path)
        tint = KIND_COLOUR.get(verdict.kind, "") if colour() else ""
        end = RESET if tint else ""
        out.append(
            f"  {short(path):<46} {tint}{bar(count / widest, 16)}{end} {size(count):>9}"
            f"  {paint(verdict.kind, DIM)}"
        )
    return out


def _inside(path: str, ancestor: str) -> bool:
    return path != ancestor and path.startswith(ancestor.rstrip("/") + "/")


def coverage_line(scanned: int, volume: Volume) -> str:
    """How much of the disk the scan actually saw.

    Scanning a home folder explains most of a personal Mac but never all of
    it: the system, the applications and other users are outside it. Saying
    so is the difference between a number and a number you can trust.
    """
    used = volume.capacity - volume.truly_free
    elsewhere = max(0, used - scanned)
    return paint(
        f"  {size(used)} in use — {size(scanned)} under the folder scanned, "
        f"{size(elsewhere)} elsewhere (system, applications, other users)",
        DIM,
    )


def changes_lines(found: Sequence[Attributed], *, limit: int = 14) -> list[str]:
    if not found:
        return ["  nothing moved by more than the noise floor"]
    out = []
    for item in found[:limit]:
        verdict = classify(item.path)
        tint = (GREEN if item.delta < 0 else AMBER) if colour() else ""
        end = RESET if tint else ""
        note = "new" if item.appeared else "gone" if item.vanished else verdict.kind
        out.append(
            f"  {tint}{size(item.delta, signed=True):>9}{end}  {short(item.path):<46}"
            f"  {paint(note, DIM)}"
        )
    return out


def forecast_line(snapshots: Sequence[Snapshot]) -> str:
    days = days_remaining(list(snapshots))
    if days is None:
        return paint("  free space is not trending down", DIM)
    when = datetime.now().timestamp() + days * 86400
    stamp = datetime.fromtimestamp(when).strftime("%-d %b")
    style = RED if days < 30 else AMBER if days < 90 else DIM
    return paint(f"  at this rate the disk is full in {days:.0f} days — around {stamp}", style)


def suggestions(entries: dict[str, int], *, limit: int = 8) -> list[str]:
    """Only caches and build output, with the command, never run."""
    out = []
    total = 0
    protected = [p for p in entries if classify(p).kind in (OFF_LIMITS, MANAGED)]
    offered: list[str] = []
    for path, count in entries.items():
        verdict = classify(path)
        if verdict.kind != RECLAIMABLE or count < (64 << 20):
            continue
        # A folder is only safe if everything inside it is. `~/.cache` looks
        # like a cache and holds the package caches that must not be touched;
        # suggesting the parent would be suggesting its protected children.
        if any(_inside(child, path) for child in protected):
            continue
        # Nor list a folder already covered by one above it: the same
        # gigabytes twice, and a total that adds up to more than the disk.
        if any(_inside(path, taken) for taken in offered):
            continue
        offered.append(path)
        total += count
        out.append(f"  {size(count):>9}  {short(path)}")
        out.append(f"             {paint(verdict.why, DIM)}")
        if verdict.command:
            out.append(f"             {verdict.command}")
        if len(out) >= limit * 3:
            break
    if not out:
        return ["  nothing here is safe to suggest removing"]
    return [f"  {paint(f'about {size(total)} is cache or build output', BOLD)}", "", *out]
