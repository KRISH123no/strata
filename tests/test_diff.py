"""Attribution: charging a change to the directory that actually caused it."""

import pytest
from conftest import GB, MB, snapshot

from strata.diff import NOISE, attribute, changes, days_remaining, free_trend


def deltas(before, after, **kwargs):
    return {a.path: a.delta for a in attribute(changes(before, after), **kwargs)}


def test_a_path_that_grew_is_reported():
    before = snapshot({"/home": 1 * GB, "/home/cache": 1 * GB})
    after = snapshot({"/home": 3 * GB, "/home/cache": 3 * GB})
    assert deltas(before, after) == {"/home/cache": 2 * GB}


def test_the_same_growth_is_not_printed_once_per_ancestor():
    """The whole report is useless if it says 2 GB four times."""
    before = snapshot({"/home": 1 * GB, "/home/.cache": 1 * GB, "/home/.cache/uv": 1 * GB})
    after = snapshot({"/home": 3 * GB, "/home/.cache": 3 * GB, "/home/.cache/uv": 3 * GB})
    assert deltas(before, after) == {"/home/.cache/uv": 2 * GB}


def test_a_parent_appears_when_it_grew_for_its_own_reasons():
    """1 GB in the child, 1 GB somewhere else in the parent."""
    before = snapshot({"/home": 0, "/home/a": 0})
    after = snapshot({"/home": 2 * GB, "/home/a": 1 * GB})
    assert deltas(before, after) == {"/home/a": 1 * GB, "/home": 1 * GB}


def test_two_siblings_are_each_charged_their_own():
    before = snapshot({"/home": 0, "/home/a": 0, "/home/b": 0})
    after = snapshot({"/home": 3 * GB, "/home/a": 1 * GB, "/home/b": 2 * GB})
    assert deltas(before, after) == {"/home/b": 2 * GB, "/home/a": 1 * GB}


def test_a_deletion_is_reported_as_a_negative():
    before = snapshot({"/home": 5 * GB, "/home/junk": 5 * GB})
    after = snapshot({"/home": 1 * GB, "/home/junk": 1 * GB})
    assert deltas(before, after) == {"/home/junk": -4 * GB}


def test_something_new_is_flagged_as_new():
    before = snapshot({"/home": 0})
    after = snapshot({"/home": 2 * GB, "/home/fresh": 2 * GB})
    found = attribute(changes(before, after))
    assert found[0].path == "/home/fresh" and found[0].appeared


def test_something_removed_entirely_is_flagged_as_gone():
    before = snapshot({"/home": 2 * GB, "/home/old": 2 * GB})
    after = snapshot({"/home": 0})
    found = [a for a in attribute(changes(before, after)) if a.path == "/home/old"]
    assert found and found[0].vanished


def test_small_churn_is_not_reported():
    before = snapshot({"/home": 1 * GB, "/home/logs": 1 * GB})
    after = snapshot({"/home": 1 * GB + 2 * MB, "/home/logs": 1 * GB + 2 * MB})
    assert deltas(before, after) == {}


def test_a_child_under_the_floor_still_explains_its_parent():
    """Otherwise the parent is charged for churn nobody can act on."""
    before = snapshot({"/home": 0, "/home/logs": 0})
    after = snapshot({"/home": 4 * MB, "/home/logs": 4 * MB})
    assert deltas(before, after, noise=NOISE) == {}


def test_the_biggest_mover_comes_first():
    before = snapshot({"/home": 0, "/home/a": 0, "/home/b": 0})
    after = snapshot({"/home": 9 * GB, "/home/a": 1 * GB, "/home/b": 8 * GB})
    assert next(a.path for a in attribute(changes(before, after))) == "/home/b"


def test_a_shrink_ranks_alongside_a_growth():
    """Both are news. A report that only shows growth hides the thing you did."""
    before = snapshot({"/home": 9 * GB, "/home/a": 9 * GB, "/home/b": 0})
    after = snapshot({"/home": 2 * GB, "/home/a": 0, "/home/b": 2 * GB})
    paths = [a.path for a in attribute(changes(before, after))]
    assert paths[0] == "/home/a"


def test_nothing_changed_is_an_empty_report():
    same = snapshot({"/home": 1 * GB, "/home/a": 1 * GB})
    assert attribute(changes(same, same)) == []


def test_the_total_is_kept_alongside_the_attributed_part():
    before = snapshot({"/home": 0, "/home/a": 0})
    after = snapshot({"/home": 2 * GB, "/home/a": 1 * GB})
    home = next(a for a in attribute(changes(before, after)) if a.path == "/home")
    assert home.delta == 1 * GB and home.total_delta == 2 * GB


# ------------------------------------------------------------- forecasting


def test_a_steady_loss_gives_a_rate_per_day():
    day = 86400.0
    series = [snapshot({}, taken=day * n, free=int(10 * GB - n * GB)) for n in range(5)]
    assert free_trend(series) == pytest.approx(-float(GB), rel=0.01)


def test_one_scan_forecasts_nothing():
    assert free_trend([snapshot({}, free=GB)]) == 0.0
    assert days_remaining([snapshot({}, free=GB)]) is None


def test_a_disk_that_is_emptying_has_no_deadline():
    day = 86400.0
    series = [snapshot({}, taken=day * n, free=int(GB + n * GB)) for n in range(4)]
    assert days_remaining(series) is None


def test_the_line_is_fitted_not_taken_from_the_ends():
    """One big delete on the last day must not cancel a week of growth."""
    day = 86400.0
    series = [snapshot({}, taken=day * n, free=int(10 * GB - n * GB)) for n in range(6)]
    series.append(snapshot({}, taken=day * 6, free=int(9 * GB)))
    assert free_trend(series) < 0, "still trending down despite the last reading"


def test_days_remaining_counts_down_from_the_last_reading():
    day = 86400.0
    series = [snapshot({}, taken=day * n, free=int(10 * GB - n * GB)) for n in range(5)]
    assert days_remaining(series) == pytest.approx(6.0, rel=0.05)


def test_a_gap_in_the_tree_does_not_lose_the_change():
    """Directories under the floor are not stored, so the chain has holes."""
    before = snapshot({"/home": 0, "/home/a/b/c": 0})
    after = snapshot({"/home": 2 * GB, "/home/a/b/c": 2 * GB})
    assert deltas(before, after) == {"/home/a/b/c": 2 * GB}


def test_a_deep_chain_charges_only_the_deepest():
    paths = ["/home", "/home/a", "/home/a/b", "/home/a/b/c", "/home/a/b/c/d"]
    before = snapshot(dict.fromkeys(paths, 0))
    after = snapshot(dict.fromkeys(paths, 3 * GB))
    assert deltas(before, after) == {"/home/a/b/c/d": 3 * GB}
