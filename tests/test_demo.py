"""The pretend history has to behave like a real one."""

import os

from strata.demo import build
from strata.diff import attribute, changes
from strata.store import Store


def snapshots():
    store = Store(":memory:")
    build(store)
    return store.all()


def test_a_parent_always_holds_at_least_its_children():
    """A tree where a child is bigger than its parent is impossible, and it
    makes the attribution report a parent that shrank while filling up."""
    for snapshot in snapshots():
        for path, size in snapshot.entries.items():
            children = [
                other for other in snapshot.entries
                if os.path.dirname(other) == path and other != path
            ]
            assert size >= sum(snapshot.entries[c] for c in children), path


def test_the_week_has_something_to_report():
    series = snapshots()
    moved = attribute(changes(series[-8], series[-1]))
    assert len(moved) >= 4


def test_both_a_growth_and_a_deletion_show_up():
    series = snapshots()
    deltas = [a.delta for a in attribute(changes(series[0], series[-1]))]
    assert max(deltas) > 0 and min(deltas) < 0


def test_free_space_trends_down_so_the_forecast_says_something():
    from strata.diff import days_remaining

    assert days_remaining(snapshots()) is not None
