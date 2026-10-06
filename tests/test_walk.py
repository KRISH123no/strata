"""Sizing a tree, counting each file once."""

import os

from conftest import MB, tree

from strata.walk import FLOOR, highlights, walk

BIG = 2 * MB


def sized(root, **kwargs):
    return walk(str(root), floor=0, **kwargs)


def test_every_file_is_counted(tmp_path):
    tree(tmp_path, {"a.bin": 1000, "deep/b.bin": 2000})
    result = sized(tmp_path)
    assert result.files == 2 and result.total == 3000


def test_a_directory_carries_everything_beneath_it(tmp_path):
    tree(tmp_path, {"a/x.bin": 1000, "a/b/y.bin": 2000})
    sizes = sized(tmp_path).sizes
    assert sizes[str(tmp_path / "a")] == 3000
    assert sizes[str(tmp_path / "a" / "b")] == 2000


def test_a_hard_link_is_one_file_not_two(tmp_path):
    """`du` reports it twice; the disk holds it once."""
    tree(tmp_path, {"original.bin": 5000})
    os.link(tmp_path / "original.bin", tmp_path / "another-name.bin")
    result = sized(tmp_path)
    assert result.total == 5000
    assert result.duplicate_bytes == 5000


def test_a_symlink_adds_nothing(tmp_path):
    tree(tmp_path, {"real.bin": 4000})
    (tmp_path / "pointer.bin").symlink_to(tmp_path / "real.bin")
    assert sized(tmp_path).total == 4000


def test_an_unreadable_folder_is_counted_not_fatal(tmp_path):
    """Half a walk that aborted looks like an answer and is not one."""
    tree(tmp_path, {"fine/a.bin": 1000, "locked/b.bin": 1000})
    locked = tmp_path / "locked"
    locked.chmod(0o000)
    try:
        result = sized(tmp_path)
        assert result.unreadable >= 1
        assert result.sizes[str(tmp_path / "fine")] == 1000
    finally:
        locked.chmod(0o755)


def test_skipped_paths_are_never_entered(tmp_path):
    tree(tmp_path, {"keep/a.bin": 1000, "nope/b.bin": 9000})
    result = sized(tmp_path, skip=[str(tmp_path / "nope")])
    assert result.total == 1000


def test_small_folders_are_folded_into_their_parent(tmp_path):
    tree(tmp_path, {"big/a.bin": BIG, "big/tiny/b.bin": 10})
    sizes = walk(str(tmp_path), floor=FLOOR).sizes
    assert str(tmp_path / "big" / "tiny") not in sizes


def test_the_root_is_always_reported(tmp_path):
    tree(tmp_path, {"a.bin": 10})
    assert str(tmp_path) in walk(str(tmp_path), floor=FLOOR).sizes


def test_nothing_is_counted_past_the_depth_limit(tmp_path):
    tree(tmp_path, {"a/b/c/d/e/f/g/deep.bin": BIG})
    sizes = walk(str(tmp_path), floor=0, max_depth=3).sizes
    assert str(tmp_path / "a" / "b" / "c") in sizes
    assert str(tmp_path / "a" / "b" / "c" / "d" / "e") not in sizes
    assert sizes[str(tmp_path)] == BIG, "the bytes still count, the path is just not named"


def test_an_empty_tree_is_not_an_error(tmp_path):
    result = sized(tmp_path)
    assert result.total == 0 and result.files == 0


# ------------------------------------------------------------- highlights


def test_a_directory_and_its_child_are_not_both_listed():
    """Otherwise the same gigabyte is printed once per level of nesting."""
    sizes = {"/h": 10, "/h/a": 9, "/h/a/b": 9, "/h/a/b/c": 9}
    assert highlights(sizes, root="/h") == [("/h/a", 9)]


def test_siblings_are_both_listed():
    sizes = {"/h": 10, "/h/a": 6, "/h/b": 4}
    assert highlights(sizes, root="/h") == [("/h/a", 6), ("/h/b", 4)]


def test_the_root_itself_is_never_a_row():
    assert highlights({"/h": 10, "/h/a": 10}, root="/h") == [("/h/a", 10)]


def test_a_similar_prefix_is_not_a_child():
    """`~/.antigravity` and `~/.antigravity-ide` are different folders."""
    sizes = {"/h": 10, "/h/.ag": 5, "/h/.ag-ide": 5}
    assert len(highlights(sizes, root="/h")) == 2


def test_the_limit_is_respected():
    sizes = {"/h": 100} | {f"/h/{n}": 10 - n for n in range(9)}
    assert len(highlights(sizes, root="/h", limit=3)) == 3


# ----------------------------------------------------- the private folders


def test_documents_is_left_alone_by_default(tmp_path, monkeypatch):
    """A nightly job must not ask for access to someone's documents."""
    monkeypatch.setenv("HOME", str(tmp_path))
    tree(tmp_path, {"Documents/private.bin": BIG, "code/a.bin": 1000})
    result = walk(str(tmp_path), floor=0)
    assert result.total == 1000
    assert str(tmp_path / "Documents") not in result.sizes


def test_it_can_be_asked_for_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    tree(tmp_path, {"Documents/private.bin": 2000, "code/a.bin": 1000})
    assert walk(str(tmp_path), floor=0, include_private=True).total == 3000


def test_the_gated_folders_are_named(tmp_path, monkeypatch):
    from strata.walk import private_paths

    monkeypatch.setenv("HOME", str(tmp_path))
    assert str(tmp_path / "Documents") in private_paths()
