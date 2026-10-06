"""The commands, and the agent that runs them nightly."""

import sys

import pytest
from conftest import GB, snapshot

from strata.cli import LABEL, _when, build_plist, main
from strata.store import Store


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


@pytest.fixture
def db(tmp_path):
    # Real clock times: `since 30d` is resolved against today, so a fixture
    # dated 1970 puts both scans on the same side of the window and they
    # collapse to one.
    import time

    now = time.time()
    path = tmp_path / "h.db"
    with Store(path) as store:
        store.save(snapshot(
            {"/h": 20 * GB, "/h/Library/Caches": 9 * GB, "/h/Pictures": 8 * GB},
            taken=now - 8 * 86400, free=20 * GB,
        ))
        store.save(snapshot(
            {"/h": 26 * GB, "/h/Library/Caches": 15 * GB, "/h/Pictures": 8 * GB},
            taken=now - 86400, free=14 * GB,
        ))
    return str(path)


def test_no_command_prints_help(capsys):
    code, out = run(capsys)
    assert code == 1 and "usage: strata" in out


def test_since_names_the_folder_that_grew(capsys, db):
    code, out = run(capsys, "--db", db, "since", "30d")
    assert code == 0 and "Caches" in out and "+6.0 GB" in out


def test_since_does_not_also_blame_the_parent(capsys, db):
    """The same six gigabytes must not appear twice."""
    _, out = run(capsys, "--db", db, "since", "30d")
    assert out.count("+6.0 GB") == 1


def test_since_reports_the_free_space_it_cost(capsys, db):
    _, out = run(capsys, "--db", db, "since", "30d")
    assert "-6.0 GB" in out


def test_one_scan_cannot_be_compared_with_itself(capsys, tmp_path):
    path = tmp_path / "one.db"
    with Store(path) as store:
        store.save(snapshot({"/h": GB}))
    code, out = run(capsys, "--db", str(path), "since", "7d")
    assert code == 1 and "only one scan" in out


def test_asking_before_any_scan_says_what_to_do(capsys, tmp_path):
    code, out = run(capsys, "--db", str(tmp_path / "empty.db"), "since", "7d")
    assert code == 1 and "strata scan" in out


def test_history_lists_every_scan(capsys, db):
    code, out = run(capsys, "--db", db, "history")
    assert code == 0 and out.count("free") == 2


def test_safe_never_suggests_your_own_files(capsys, db):
    code, out = run(capsys, "--db", db, "safe")
    assert code == 0
    assert "Pictures" not in out
    assert "Caches" in out
    assert "never deletes" in out


@pytest.mark.parametrize("text", ["7d", "2w", "yesterday", "2026-10-01"])
def test_times_people_actually_type(text):
    assert _when(text) > 0


def test_an_unparseable_time_says_what_works():
    with pytest.raises(SystemExit, match="try 7d"):
        _when("last tuesday")


# ------------------------------------------------------------------ agent


def test_the_nightly_agent_runs_a_scan():
    plist = build_plist(python="/usr/bin/python3", root="/Users/k", hour=4)
    assert LABEL in plist
    assert "<string>scan</string>" in plist
    assert "<integer>4</integer>" in plist


def test_the_agent_is_told_where_the_package_lives():
    """launchd starts from /, so a source checkout is on no import path."""
    assert "<key>PYTHONPATH</key>" in build_plist(root="/Users/k")


def test_it_is_scheduled_rather_than_kept_alive():
    """A disk scan is a nightly job, not a daemon."""
    plist = build_plist(root="/Users/k")
    assert "StartCalendarInterval" in plist and "KeepAlive" not in plist


def test_it_stays_out_of_the_way():
    plist = build_plist(root="/Users/k")
    assert "Background" in plist and "LowPriorityIO" in plist


def test_installing_off_a_mac_says_why(capsys, monkeypatch):
    import strata.cli as cli

    monkeypatch.setattr(cli.sys, "platform", "linux")
    code, out = run(capsys, "install")
    assert code == 1 and "macOS only" in out


darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


@darwin
def test_doctor_reports_the_volume(capsys, db):
    code, out = run(capsys, "--db", db, "doctor")
    assert code == 0 and "truly free" in out
