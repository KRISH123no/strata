"""Building trees and snapshots by hand, so none of this needs a real disk."""

import pytest

from strata.model import Snapshot

MB = 1 << 20
GB = 1 << 30


def snapshot(entries, *, taken=1_000_000.0, free=10 * GB, capacity=256 * GB, root="/home"):
    return Snapshot(
        taken=taken, root=root, entries=dict(entries),
        total=sum(entries.values()), free=free, capacity=capacity,
    )


def tree(root, spec):
    """``tree(tmp_path, {"a/b.bin": 2048})`` — make files of a given size."""
    for relative, count in spec.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * count)
    return root


@pytest.fixture
def store():
    from strata.store import Store

    with Store(":memory:") as db:
        yield db
