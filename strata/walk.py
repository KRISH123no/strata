"""Sizing a tree honestly.

`du` is the obvious tool and it is wrong twice on a modern Mac.

**Hard links and APFS clones are counted once per name.** A file reachable
down three paths is three files to `du` and one file to the disk. Copy a
folder in Finder and APFS clones it — no new bytes, and a naive walk reports
the space twice.

**Permission errors stop it.** Half a walk that aborted is worse than no walk,
because it looks like an answer. Anything unreadable is counted as unreadable
and the walk carries on.

What comes back is a rollup: every directory worth naming, with everything
beneath it. Keeping every directory on a real machine means millions of rows
of mostly nothing, so anything below a floor is folded into its parent — the
answer to "where did the space go" is never a path forty levels deep holding
nine kilobytes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from stat import S_ISREG

#: Directories smaller than this are folded into their parent rather than
#: being named. A tenth of a per cent of a 256 GB disk is about 256 MB; this
#: is deliberately far below that, so nothing that could matter is hidden.
FLOOR = 16 * 1024 * 1024

#: How deep to name paths. Beyond this everything rolls into the ancestor at
#: this depth — `~/Library/Caches/Chrome` is useful, forty levels under it is
#: not.
MAX_DEPTH = 6

#: Never descend into these. They are other volumes, synthetic filesystems, or
#: the places a walk goes to die.
SKIP = frozenset({"/dev", "/proc", "/sys", "/Volumes", "/net", "/System/Volumes/Data/home"})


@dataclass(slots=True)
class Walked:
    sizes: dict[str, int]
    files: int = 0
    total: int = 0
    unreadable: int = 0
    duplicate_bytes: int = 0


def walk(
    root: str,
    *,
    floor: int = FLOOR,
    max_depth: int = MAX_DEPTH,
    skip: Iterable[str] = SKIP,
    on_dir: Callable[[str], None] | None = None,
) -> Walked:
    """Size everything under ``root``, counting each file once."""
    root = os.path.abspath(os.path.expanduser(root))
    skip = {os.path.abspath(p) for p in skip}
    seen: set[tuple[int, int]] = set()
    result = Walked(sizes={})
    base_depth = root.rstrip("/").count("/")

    # Bottom-up, so a directory's children are finished before it is.
    for folder, subdirs, names in os.walk(root, topdown=True, onerror=_count(result)):
        if folder in skip:
            subdirs[:] = []
            continue
        subdirs[:] = [d for d in subdirs if os.path.join(folder, d) not in skip]

        own = 0
        for name in names:
            path = os.path.join(folder, name)
            try:
                stat = os.lstat(path)
            except OSError:
                result.unreadable += 1
                continue
            if not S_ISREG(stat.st_mode):
                continue  # a symlink or a device, not bytes on this volume
            key = (stat.st_dev, stat.st_ino)
            if key in seen:
                # Already counted under another name: a hard link, or a clone.
                result.duplicate_bytes += stat.st_size
                continue
            seen.add(key)
            own += stat.st_size
            result.files += 1

        result.total += own
        if own and on_dir:
            on_dir(folder)
        if own:
            result.sizes[folder] = result.sizes.get(folder, 0) + own

    return _rollup(result, root, base_depth, floor, max_depth)


def _count(result: Walked) -> Callable[[OSError], None]:
    def note(_error: OSError) -> None:
        result.unreadable += 1

    return note


def _rollup(result: Walked, root: str, base_depth: int, floor: int, max_depth: int) -> Walked:
    """Give every directory the total beneath it, then drop the noise."""
    totals: dict[str, int] = {}
    for path, own in result.sizes.items():
        node = path
        while True:
            totals[node] = totals.get(node, 0) + own
            if node == root or len(node) <= len(root):
                break
            node = os.path.dirname(node)

    kept = {
        path: size
        for path, size in totals.items()
        if size >= floor and path.rstrip("/").count("/") - base_depth <= max_depth
    }
    kept[root] = totals.get(root, 0)
    result.sizes = dict(sorted(kept.items(), key=lambda item: -item[1]))
    return result


def highlights(
    sizes: dict[str, int], *, root: str = "", limit: int = 14
) -> list[tuple[str, int]]:
    """The largest directories that do not contain one another.

    A plain sort by size lists a directory, then its one big child, then
    *that* child — the same gigabyte printed four times, each row a slightly
    longer path. Every row here is space that no other row also counts, so
    the column adds up to something real.
    """
    chosen: list[tuple[str, int]] = []
    for path, count in sorted(sizes.items(), key=lambda item: -item[1]):
        if path == root:
            continue
        if any(_within(path, taken) for taken, _ in chosen):
            continue
        chosen.append((path, count))
        if len(chosen) >= limit:
            break
    return chosen


def _within(path: str, ancestor: str) -> bool:
    return path == ancestor or path.startswith(ancestor.rstrip("/") + "/")
