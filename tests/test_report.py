"""What strata is willing to put its name to."""

import pytest
from conftest import GB, MB

from strata.report import bar, size, suggestions

HOME = "/Users/you"


def text(entries, **kwargs):
    return "\n".join(suggestions(entries, **kwargs))


def test_a_cache_is_offered():
    assert "Library/Caches" in text({f"{HOME}/Library/Caches": 9 * GB})


def test_your_own_files_are_never_offered():
    assert "nothing here is safe" in text({f"{HOME}/Pictures": 40 * GB})


def test_a_protected_cache_is_never_offered():
    assert "nothing here is safe" in text({f"{HOME}/.cache/uv": 9 * GB})


def test_a_folder_holding_a_protected_one_is_not_offered_either():
    """`~/.cache` looks like a cache and holds the package caches that must
    not be touched. Offering the parent offers its children."""
    out = text({f"{HOME}/.cache": 12 * GB, f"{HOME}/.cache/uv": 9 * GB})
    assert f"{HOME}/.cache\n" not in out
    assert "uv" not in out


def test_a_clean_parent_is_still_offered():
    out = text({f"{HOME}/Library/Caches": 9 * GB, f"{HOME}/Library/Caches/Chromium": 4 * GB})
    assert "Library/Caches" in out


def test_an_app_store_inside_a_cache_protects_it():
    out = text({
        f"{HOME}/.cache": 12 * GB,
        f"{HOME}/.cache/huggingface": 6 * GB,
    })
    assert "nothing here is safe" in out


def test_something_trivial_is_not_worth_mentioning():
    assert "nothing here is safe" in text({f"{HOME}/Library/Caches": 4 * MB})


def test_the_command_is_printed_when_there_is_one():
    out = text({f"{HOME}/Library/Developer/Xcode/DerivedData": 10 * GB})
    assert "rebuilt on demand" in out


# ---------------------------------------------------------------- units


@pytest.mark.parametrize(
    "count,text_",
    [(0, "0 B"), (900, "900 B"), (2048, "2.0 KB"), (5 << 20, "5.0 MB"), (3 << 30, "3.0 GB")],
)
def test_sizes_read_the_way_people_say_them(count, text_):
    assert size(count) == text_


def test_a_change_carries_its_sign():
    assert size(2 << 30, signed=True) == "+2.0 GB"
    assert size(-(2 << 30), signed=True) == "-2.0 GB"


def test_a_bar_is_always_the_width_asked_for():
    assert all(len(bar(f, 20)) == 20 for f in (0.0, 0.03, 0.5, 1.0, 5.0))


def test_a_bar_distinguishes_small_numbers():
    assert bar(0.03, 20) != bar(0.09, 20)


def test_a_folder_and_its_child_are_not_both_offered():
    """Otherwise the total adds up to more than is on the disk."""
    out = text({
        f"{HOME}/proj/.venv": 400 * MB,
        f"{HOME}/proj/.venv/lib": 390 * MB,
    })
    assert out.count(".venv") == 1


def test_the_total_only_counts_what_it_listed():
    out = text({
        f"{HOME}/proj/.venv": 1 * GB,
        f"{HOME}/proj/.venv/lib": 1 * GB,
    })
    assert "about 1.0 GB" in out
