"""What the filesystem claims, and the gap between that and the truth."""


from conftest import GB

from strata.volume import Volume, container_free, inspect, local_snapshots

DISKUTIL = """
   Device Identifier:         disk3s1s1
   Container Free Space:      12.2 GB (12227444736 Bytes) (exactly 23881728 512-Byte-Units)
   Allocation Block Size:     4096 Bytes
"""
TMUTIL = """Snapshots for disk /:
com.apple.os.update-796ED138EFB4
com.apple.TimeMachine.2026-10-06-031500.local
"""


def faker(answers):
    def run(command):
        for key, text in answers.items():
            if key in command:
                return text
        return ""

    return run


def test_the_container_free_space_is_read_from_diskutil():
    assert container_free(runner=faker({"diskutil": DISKUTIL})) == 12227444736


def test_a_machine_that_says_nothing_reports_zero_not_a_crash():
    assert container_free(runner=faker({})) == 0


def test_local_snapshots_are_listed():
    found = local_snapshots(runner=faker({"tmutil": TMUTIL}))
    assert len(found) == 2 and found[0].startswith("com.apple.os.update")


def test_no_snapshots_is_an_empty_tuple():
    assert local_snapshots(runner=faker({"tmutil": "Snapshots for disk /:\n"})) == ()


# --------------------------------------------------------------- purgeable


def test_purgeable_is_the_gap_between_what_df_says_and_what_is_there():
    """df counts space the system *could* release as already free."""
    volume = Volume(root="/", capacity=100 * GB, free=20 * GB, container_free=12 * GB)
    assert volume.purgeable == 8 * GB
    assert volume.truly_free == 12 * GB


def test_a_negative_gap_is_rounding_not_news():
    volume = Volume(root="/", capacity=100 * GB, free=12 * GB, container_free=12 * GB + 4096)
    assert volume.purgeable == 0


def test_without_diskutil_df_is_all_there_is():
    volume = Volume(root="/", capacity=100 * GB, free=20 * GB, container_free=0)
    assert volume.truly_free == 20 * GB and volume.purgeable == 0


def test_inspect_puts_it_together(tmp_path):
    volume = inspect("/", runner=faker({"diskutil": DISKUTIL, "tmutil": TMUTIL}))
    assert volume.capacity > 0
    assert volume.container_free == 12227444736
    assert len(volume.snapshots) == 2
