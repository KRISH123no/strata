"""What changed between two scans — the part a single listing cannot tell you.

One scan says what is *big*. Everyone already knows what is big: the photo
library, the browser, the virtual machines. That is not the question anyone
actually has. The question is **where did three gigabytes go since Tuesday**,
and only a history can answer it.

The hard part is not subtraction, it is **attribution**. If `~/.cache/uv`
grows by two gigabytes then so does `~/.cache`, and `~`, and `/Users`. All
four are true and reporting all four is the same two gigabytes printed four
times. A report that does that is useless, because the reader has to do the
arithmetic the tool was supposed to do.

So each directory is charged only with what its children do not explain. Walk
deepest-first, attribute the change to the most specific path that accounts
for it, and subtract it from every ancestor on the way up. A parent appears
only when it grew for reasons of its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .model import Change, Snapshot

#: Changes smaller than this are noise: a log file, a browser's idle churn.
NOISE = 32 * 1024 * 1024


@dataclass(slots=True)
class Attributed:
    """A change, charged to the directory actually responsible for it."""

    path: str
    delta: int
    #: The change including everything underneath, before attribution.
    total_delta: int
    before: int
    after: int

    @property
    def appeared(self) -> bool:
        return self.before == 0 and self.after > 0

    @property
    def vanished(self) -> bool:
        return self.after == 0 and self.before > 0


def changes(before: Snapshot, after: Snapshot) -> list[Change]:
    """Every path that differs, including ones that came or went."""
    paths = set(before.entries) | set(after.entries)
    found = [
        Change(path, before.entries.get(path, 0), after.entries.get(path, 0))
        for path in paths
    ]
    return [c for c in found if c.delta != 0]


def attribute(found: list[Change], *, noise: int = NOISE) -> list[Attributed]:
    """Charge each change to the deepest directory that explains it.

    Deepest-first, so that by the time a parent is considered, everything
    beneath it that was worth naming has already been taken out of its total.
    """
    by_path = {c.path: c for c in found}
    ordered = sorted(by_path, key=lambda p: (-p.count(os.sep), p))
    claimed: dict[str, int] = {}
    out: list[Attributed] = []

    for path in ordered:
        change = by_path[path]
        # Anything already charged to a directory beneath this one.
        explained = claimed.get(path, 0)
        residual = change.delta - explained
        if abs(residual) < noise:
            # Nothing of its own; pass the whole total up so the parent is
            # not charged for it either.
            _pass_up(claimed, by_path, path, change.delta)
            continue

        out.append(
            Attributed(
                path=path,
                delta=residual,
                total_delta=change.delta,
                before=change.before,
                after=change.after,
            )
        )
        _pass_up(claimed, by_path, path, change.delta)

    return sorted(out, key=lambda item: -abs(item.delta))


def _pass_up(claimed: dict[str, int], known: dict[str, Change], path: str, delta: int) -> None:
    """Charge this total to the nearest ancestor that is itself reported.

    Only the nearest, not all of them. An ancestor's own figure already
    includes everything beneath it and it will pass that figure up in its
    turn, so charging every generation counts the same bytes once per level —
    which is how a grandparent ends up with a change of minus two gigabytes
    that never happened.

    "Nearest *reported*" matters too: directories under the floor are not
    stored, so the chain has gaps, and stopping at the first missing link
    would leave the growth charged to nobody.
    """
    parent = os.path.dirname(path)
    while parent and parent != path:
        if parent in known:
            claimed[parent] = claimed.get(parent, 0) + delta
            return
        path, parent = parent, os.path.dirname(parent)


def free_trend(snapshots: list[Snapshot]) -> float:
    """Bytes of free space gained or lost per day, by least squares.

    A straight line through every reading, not the difference between the
    first and the last — one scan taken straight after a big delete would
    otherwise set the forecast for the whole week.
    """
    usable = [s for s in snapshots if s.free and s.taken]
    if len(usable) < 2:
        return 0.0

    days = [s.taken / 86400 for s in usable]
    frees = [float(s.free) for s in usable]
    mean_day = sum(days) / len(days)
    mean_free = sum(frees) / len(frees)

    spread = sum((d - mean_day) ** 2 for d in days)
    if spread == 0:
        return 0.0
    covariance = sum((d - mean_day) * (f - mean_free) for d, f in zip(days, frees, strict=True))
    return covariance / spread


def days_remaining(snapshots: list[Snapshot]) -> float | None:
    """At this rate, how long until the disk is full? None if it is not filling."""
    if not snapshots:
        return None
    rate = free_trend(snapshots)
    if rate >= 0:
        return None
    return snapshots[-1].free / -rate
