"""What strata deals in: an entry, a snapshot, and a change between two.

Nothing here knows about macOS or about disks. The interesting work — rolling
a tree up, comparing two scans, deciding what a change really means — is
arithmetic over these three, which is why it is all testable without a disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Entry:
    """One directory, and everything beneath it."""

    path: str
    bytes: int = 0
    files: int = 0
    #: Directories counted once each, however many names point at them.
    depth: int = 0

    def __lt__(self, other: Entry) -> bool:
        return self.bytes < other.bytes


@dataclass(slots=True)
class Snapshot:
    """One scan: when it ran, what the volume looked like, what was where."""

    taken: float
    root: str
    entries: dict[str, int] = field(default_factory=dict)
    files: int = 0
    #: Total bytes under the root, deduplicated.
    total: int = 0
    #: From the volume, not the walk: what the filesystem itself reports.
    free: int = 0
    capacity: int = 0
    #: Bytes held by APFS local snapshots — invisible to a walk and to Finder.
    snapshot_bytes: int = 0
    id: int | None = None

    @property
    def used(self) -> int:
        return self.capacity - self.free


@dataclass(slots=True)
class Change:
    """How one path differed between two snapshots."""

    path: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before

    @property
    def appeared(self) -> bool:
        return self.before == 0 and self.after > 0

    @property
    def vanished(self) -> bool:
        return self.after == 0 and self.before > 0
