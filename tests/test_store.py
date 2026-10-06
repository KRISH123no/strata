"""Keeping the history, which is the only thing this tool really owns."""


from conftest import GB, snapshot

from strata.store import Store


def test_a_snapshot_survives_the_round_trip(store):
    saved = snapshot({"/h": 5 * GB, "/h/a": 3 * GB}, free=7 * GB)
    store.save(saved)
    back = store.latest()
    assert back.entries == saved.entries
    assert back.free == 7 * GB and back.total == 8 * GB


def test_the_latest_is_the_newest_not_the_last_written(store):
    store.save(snapshot({"/h": 1}, taken=2000.0))
    store.save(snapshot({"/h": 2}, taken=1000.0))
    assert store.latest().taken == 2000.0


def test_an_earlier_scan_can_be_reached_by_offset(store):
    store.save(snapshot({"/h": 1}, taken=1000.0))
    store.save(snapshot({"/h": 2}, taken=2000.0))
    assert store.latest(offset=1).taken == 1000.0


def test_the_nearest_scan_to_a_moment_is_found(store):
    for when in (1000.0, 5000.0, 9000.0):
        store.save(snapshot({"/h": 1}, taken=when))
    assert store.nearest(5400.0).taken == 5000.0


def test_nearest_looks_both_ways(store):
    """Asking about a day you did not scan must not answer about a different week."""
    store.save(snapshot({"/h": 1}, taken=9000.0))
    assert store.nearest(1000.0).taken == 9000.0


def test_an_empty_history_has_no_latest(store):
    assert store.latest() is None and store.nearest(0) is None


def test_scans_come_back_in_order(store):
    for when in (3000.0, 1000.0, 2000.0):
        store.save(snapshot({"/h": 1}, taken=when))
    assert [s.taken for s in store.all()] == [1000.0, 2000.0, 3000.0]


def test_pruning_drops_the_old_and_keeps_the_recent(store):
    import time

    now = time.time()
    store.save(snapshot({"/h": 1}, taken=now - 500 * 86400))
    store.save(snapshot({"/h": 1}, taken=now - 1 * 86400))
    assert store.prune(keep_days=400) == 1
    assert store.count() == 1


def test_pruning_takes_the_sizes_with_it(store):
    """A scan's rows must not outlive the scan."""
    import time

    store.save(snapshot({"/h": 1, "/h/a": 1}, taken=time.time() - 500 * 86400))
    store.prune(keep_days=400)
    assert store.db.execute("SELECT COUNT(*) FROM sizes").fetchone()[0] == 0


def test_a_file_backed_history_survives_reopening(tmp_path):
    path = tmp_path / "h.db"
    with Store(path) as first:
        first.save(snapshot({"/h": 4 * GB}))
    with Store(path) as second:
        assert second.latest().entries == {"/h": 4 * GB}


def test_saving_returns_an_id_and_stamps_it(store):
    saved = snapshot({"/h": 1})
    assert store.save(saved) == saved.id
