"""Checking the protections macOS already has, rather than selling another one.

A third-party antivirus on a Mac usually adds a kernel extension, scans files
the system already vets, and costs performance for it. Meanwhile four
protections ship with the machine and do the actual work — and the only
honest question is whether they are switched on.

The second question is the one a scanner cannot answer and a history can:
**what has started launching itself since last time?** Malware on macOS
persists through the same launchd mechanism as everything else. Nothing here
decides whether a launch agent is good or bad; it reports what is new, which
is the thing you can actually judge.
"""

from __future__ import annotations

import os
import plistlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .volume import run

Runner = Callable[[list[str]], str]

XPROTECT = Path(
    "/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist"
)

#: Where things arrange to start themselves. User-level first: it is the one
#: a process can write to without a password, so it is where anything
#: unwelcome lands.
PERSISTENCE = (
    "~/Library/LaunchAgents",
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
)


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    why: str = ""


@dataclass(slots=True)
class Posture:
    checks: list[Check] = field(default_factory=list)
    #: Every plist that arranges for something to launch itself.
    persistence: list[str] = field(default_factory=list)

    @property
    def failing(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def ok(self) -> bool:
        return not self.failing


def sip(*, runner: Runner = run) -> Check:
    text = runner(["csrutil", "status"]).lower()
    on = "enabled" in text and "disabled" not in text
    return Check(
        "System Integrity Protection", on,
        "enabled" if on else "DISABLED",
        "stops even an administrator modifying the system — turning it off is a deliberate act",
    )


def filevault(*, runner: Runner = run) -> Check:
    text = runner(["fdesetup", "status"]).lower()
    on = "on" in text and "off" not in text.replace("status:", "")
    return Check(
        "FileVault", on, "on" if on else "OFF",
        "without it the disk is readable by anyone who takes the machine",
    )


def gatekeeper(*, runner: Runner = run) -> Check:
    text = runner(["spctl", "--status"]).lower()
    on = "assessments enabled" in text
    return Check(
        "Gatekeeper", on, "enabled" if on else "DISABLED",
        "checks that an app is signed and notarised before it first runs",
    )


def xprotect(path: Path = XPROTECT) -> Check:
    """Apple's own malware definitions, which update themselves."""
    try:
        with open(path, "rb") as handle:
            version = plistlib.load(handle).get("CFBundleShortVersionString", "")
    except (OSError, plistlib.InvalidFileException):
        return Check("XProtect", False, "not found",
                     "macOS ships malware definitions and updates them silently")
    return Check("XProtect", bool(version), f"version {version}",
                 "Apple's malware definitions, updated without asking")


def persistence_items(folders=PERSISTENCE) -> list[str]:
    """Everything that has arranged to start itself, by path.

    Sorted, because this list is compared against the one from last night and
    a different order would read as a change.
    """
    found: list[str] = []
    for folder in folders:
        base = Path(os.path.expanduser(folder))
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        found.extend(
            str(entry) for entry in entries
            if entry.suffix == ".plist" and not entry.name.startswith(".")
        )
    return sorted(found)


def audit(*, runner: Runner = run, xprotect_path: Path = XPROTECT) -> Posture:
    return Posture(
        checks=[
            sip(runner=runner),
            filevault(runner=runner),
            gatekeeper(runner=runner),
            xprotect(xprotect_path),
        ],
        persistence=persistence_items(),
    )


def appeared(before: list[str], after: list[str]) -> list[str]:
    """What has started launching itself since last time."""
    return sorted(set(after) - set(before))


def disappeared(before: list[str], after: list[str]) -> list[str]:
    return sorted(set(before) - set(after))
