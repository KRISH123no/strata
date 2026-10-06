"""Checking what macOS already has, and noticing what is new."""

import plistlib

import pytest

from strata.security import (
    appeared,
    audit,
    disappeared,
    filevault,
    gatekeeper,
    persistence_items,
    sip,
    xprotect,
)


def faker(**answers):
    def run(command):
        return answers.get(command[0], "")

    return run


ON = faker(
    csrutil="System Integrity Protection status: enabled.",
    fdesetup="FileVault is On.",
    spctl="assessments enabled",
)
OFF = faker(
    csrutil="System Integrity Protection status: disabled.",
    fdesetup="FileVault is Off.",
    spctl="assessments disabled",
)


@pytest.mark.parametrize("check", [sip, filevault, gatekeeper])
def test_a_protected_machine_passes(check):
    assert check(runner=ON).ok


@pytest.mark.parametrize("check", [sip, filevault, gatekeeper])
def test_an_unprotected_one_does_not(check):
    result = check(runner=OFF)
    assert not result.ok and result.why, "a failure has to say why it matters"


@pytest.mark.parametrize("check", [sip, filevault, gatekeeper])
def test_a_machine_that_answers_nothing_is_not_assumed_safe(check):
    assert not check(runner=faker()).ok


def test_xprotect_reports_its_version(tmp_path):
    path = tmp_path / "Info.plist"
    path.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "5363"}))
    result = xprotect(path)
    assert result.ok and "5363" in result.detail


def test_a_missing_xprotect_is_a_finding_not_a_crash(tmp_path):
    assert not xprotect(tmp_path / "nope.plist").ok


def test_a_corrupt_plist_does_not_take_the_audit_down(tmp_path):
    path = tmp_path / "Info.plist"
    path.write_bytes(b"this is not a plist")
    assert not xprotect(path).ok


# ------------------------------------------------------------ persistence


def test_launch_agents_are_listed(tmp_path):
    (tmp_path / "a.plist").write_text("x")
    (tmp_path / "b.plist").write_text("x")
    assert len(persistence_items([str(tmp_path)])) == 2


def test_only_plists_count(tmp_path):
    (tmp_path / "a.plist").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden.plist").write_text("x")
    assert len(persistence_items([str(tmp_path)])) == 1


def test_a_folder_that_is_not_there_is_not_an_error(tmp_path):
    assert persistence_items([str(tmp_path / "nope")]) == []


def test_the_list_is_sorted_so_order_is_never_mistaken_for_change(tmp_path):
    for name in ("z.plist", "a.plist", "m.plist"):
        (tmp_path / name).write_text("x")
    found = persistence_items([str(tmp_path)])
    assert found == sorted(found)


def test_something_new_is_noticed():
    before = ["/a.plist", "/b.plist"]
    after = ["/a.plist", "/b.plist", "/evil.plist"]
    assert appeared(before, after) == ["/evil.plist"]


def test_something_removed_is_noticed_too():
    assert disappeared(["/a.plist", "/b.plist"], ["/a.plist"]) == ["/b.plist"]


def test_no_change_is_no_news():
    same = ["/a.plist"]
    assert appeared(same, same) == [] and disappeared(same, same) == []


def test_the_audit_puts_it_together():
    posture = audit(runner=ON)
    assert len(posture.checks) == 4
    assert all(c.name for c in posture.checks)


def test_a_failing_audit_names_what_failed():
    posture = audit(runner=OFF)
    assert not posture.ok
    assert {c.name for c in posture.failing} >= {"FileVault", "Gatekeeper"}
