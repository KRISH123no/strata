"""What a directory is, and whether strata is allowed to suggest removing it."""

import pytest

from strata.classify import (
    MANAGED,
    OFF_LIMITS,
    RECLAIMABLE,
    YOURS,
    classify,
    safe_to_suggest,
)


@pytest.mark.parametrize(
    "path,kind",
    [
        ("/Users/k/Library/Caches/Google", RECLAIMABLE),
        ("/Users/k/code/app/node_modules", RECLAIMABLE),
        ("/Users/k/Library/Developer/Xcode/DerivedData", RECLAIMABLE),
        ("/Users/k/Library/Containers/com.amazon.aiv.AIVApp/Data", MANAGED),
        ("/Users/k/Library/Application Support/Spotify/PersistentCache", MANAGED),
        ("/Users/k/.cache/huggingface/hub", MANAGED),
        ("/Users/k/Desktop/github", YOURS),
        ("/Users/k/Pictures", YOURS),
        ("/Users/k/.cache/uv/archive-v0", OFF_LIMITS),
        ("/Users/k/.npm/_cacache", OFF_LIMITS),
    ],
)
def test_directories_are_recognised(path, kind):
    assert classify(path).kind == kind


def test_the_uv_cache_is_protected_even_though_it_is_called_a_cache():
    """It matches the generic cache rule; the specific rule has to win."""
    assert classify("/Users/k/.cache/uv").kind == OFF_LIMITS
    assert not safe_to_suggest("/Users/k/.cache/uv")


def test_a_protected_cache_still_gets_a_safe_command():
    assert "prune" in classify("/Users/k/.cache/uv").command


def test_nothing_of_yours_is_ever_suggested():
    for path in ("/Users/k/Documents", "/Users/k/Desktop/paper", "/Users/k/Pictures/2024"):
        assert not safe_to_suggest(path)


def test_an_application_store_is_not_suggested_either():
    """Deleting it under the app's feet corrupts its database."""
    assert not safe_to_suggest("/Users/k/Library/Containers/com.amazon.aiv.AIVApp")


def test_only_caches_and_build_output_are_suggested():
    assert safe_to_suggest("/Users/k/Library/Caches/Chromium")
    assert safe_to_suggest("/Users/k/src/thing/build")


def test_something_unrecognised_is_not_guessed_at():
    verdict = classify("/Users/k/the-entity-ml")
    assert verdict.kind == "unknown" and not safe_to_suggest("/Users/k/the-entity-ml")


def test_an_app_that_mentions_a_browser_is_managed_not_wiped():
    assert classify("/Users/k/Library/Application Support/Google/Chrome").kind == MANAGED
