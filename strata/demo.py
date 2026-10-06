"""A week of pretend scans, so the tool can be seen before you have a history.

Everything strata is for only appears on the second scan. That makes it a
hard thing to show, and a hard thing to believe: the first run of a disk tool
looks exactly like every other disk tool. This builds a fortnight that behaves
the way a fortnight does — a cache creeping up, a video app quietly hoarding,
something large deleted on a Thursday — and runs it through the same reporting
code your own scans go through.
"""

from __future__ import annotations

import time

from .model import Snapshot
from .store import Store

GB = 1 << 30
HOME = "/Users/you"

#: Leaves only: (path, starting size, bytes added per day). Every ancestor is
#: computed from these, because in a real tree a directory always holds at
#: least the sum of its children — and inventing a parent total independently
#: produces a parent that shrank while its contents grew, which the
#: attribution correctly reports as nonsense.
LEAVES = [
    (f"{HOME}/Library/Caches", 8 * GB, 380 << 20),
    (f"{HOME}/Library/Containers/com.amazon.aiv.AIVApp", 4 * GB, 900 << 20),
    (f"{HOME}/Library/Application Support/Spotify/PersistentCache", 4 * GB, 40 << 20),
    (f"{HOME}/Library/Developer/CoreSimulator", 12 * GB, 120 << 20),
    (f"{HOME}/.cache/uv", 9 * GB, 25 << 20),
    (f"{HOME}/.cache/huggingface", 2 * GB, 60 << 20),
    (f"{HOME}/Pictures", 16 * GB, 30 << 20),
    (f"{HOME}/Desktop", 12 * GB, 0),
    (f"{HOME}/Downloads", 9 * GB, 210 << 20),
    (f"{HOME}/code/app/node_modules", 3 * GB, 0),
]

#: Day 11: a large download is deleted, so a shrink shows up in the report too.
CLEARED = (f"{HOME}/Downloads", 11, 5 * GB)


def build(store: Store, *, days: int = 14) -> int:
    import os

    now = time.time()
    for day in range(days):
        entries: dict[str, int] = {}
        for path, start, per_day in LEAVES:
            size = start + per_day * day
            if path == CLEARED[0] and day >= CLEARED[1]:
                size -= CLEARED[2]
            # Roll the leaf up into every ancestor, the way a real walk does.
            node = path
            while node.startswith(HOME):
                entries[node] = entries.get(node, 0) + size
                if node == HOME:
                    break
                node = os.path.dirname(node)

        total = entries[HOME]
        store.save(
            Snapshot(
                taken=now - (days - 1 - day) * 86400,
                root=HOME,
                entries=entries,
                files=900_000 + day * 2_000,
                total=total,
                free=int(18 * GB - day * 1.1 * GB) + (5 * GB if day >= CLEARED[1] else 0),
                capacity=245 * GB,
            )
        )
    return days
