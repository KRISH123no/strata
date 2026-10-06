"""What the filesystem says about itself, as opposed to what a walk finds.

The two disagree, and the gap is the interesting part.

**`df` counts purgeable space as free.** On APFS, space held by caches and
local snapshots that the system *could* release is reported as available. The
number is a promise, not a fact, and you discover the difference when a copy
fails on a disk that said it had room.

**Local snapshots are invisible.** Time Machine leaves them on the boot
volume; they hold real gigabytes and appear in no walk, in Finder, or in About
This Mac. They are a large part of what Apple files under "System Data".

Everything here shells out to tools that ship with macOS, so strata needs no
dependencies at all — and each command is a seam that a test can replace.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

Runner = Callable[[list[str]], str]

_BYTES = re.compile(r"\((\d+)\s+Bytes\)")
_SNAPSHOT = re.compile(r"^(com\.apple\.\S+)", re.MULTILINE)


def run(command: list[str]) -> str:
    """Run a system tool, returning "" rather than raising."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""


@dataclass(slots=True)
class Volume:
    root: str
    capacity: int = 0
    #: What `df` claims, which includes space that is only theoretically free.
    free: int = 0
    #: What the container actually has unallocated.
    container_free: int = 0
    snapshots: tuple[str, ...] = ()

    @property
    def used(self) -> int:
        return self.capacity - self.free

    @property
    def purgeable(self) -> int:
        """The gap between the promise and the fact.

        Negative gaps are rounding between two tools that measure slightly
        different things, and are reported as nothing rather than as a
        mysterious negative quantity.
        """
        return max(0, self.free - self.container_free) if self.container_free else 0

    @property
    def truly_free(self) -> int:
        return self.container_free or self.free


def capacity_and_free(root: str = "/") -> tuple[int, int]:
    stat = os.statvfs(root)
    return stat.f_blocks * stat.f_frsize, stat.f_bavail * stat.f_frsize


def container_free(root: str = "/", *, runner: Runner = run) -> int:
    """What `diskutil` says is unallocated, which `df` does not tell you."""
    for line in runner(["diskutil", "info", root]).splitlines():
        if "Container Free Space" in line or "Volume Free Space" in line:
            found = _BYTES.search(line)
            if found:
                return int(found.group(1))
    return 0


def local_snapshots(root: str = "/", *, runner: Runner = run) -> tuple[str, ...]:
    """Time Machine's local snapshots — real bytes, in no walk and no window."""
    return tuple(_SNAPSHOT.findall(runner(["tmutil", "listlocalsnapshots", root])))


def inspect(root: str = "/", *, runner: Runner = run) -> Volume:
    capacity, free = capacity_and_free(root)
    return Volume(
        root=root,
        capacity=capacity,
        free=free,
        container_free=container_free(root, runner=runner),
        snapshots=local_snapshots(root, runner=runner),
    )
