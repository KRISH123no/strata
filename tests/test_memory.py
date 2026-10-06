"""Memory: reading the state, and telling a leak from an afternoon's work."""

import pytest
from conftest import GB, MB

from strata.memory import (
    Memory,
    _app_name,
    growth,
    parse_vm_stat,
    read,
    top_processes,
)

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     4153.
Pages active:                                 400000.
Pages wired down:                             142631.
Pages stored in compressor:                  1221838.
Pages occupied by compressor:                 476028.
Compressions:                              397399780.
Decompressions:                            379034252.
Swapins:                                     6341213.
Swapouts:                                     546644.
"""
SWAP = "vm.swapusage: total = 2048.00M  used = 1685.06M  free = 362.94M  (encrypted)\n"
PRESSURE = "System-wide memory free percentage: 38%\n"
PS = """ 432480 /Applications/Google Chrome.app/Contents/Frameworks/Helper (Renderer)
 300448 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
 426048 /Applications/Claude.app/Contents/Frameworks/Claude Helper
   1024 /usr/sbin/cupsd
"""


def faker(**answers):
    def run(command):
        return answers.get(command[0], "")

    return run


RUNNER = faker(vm_stat=VM_STAT, sysctl=SWAP, memory_pressure=PRESSURE, ps=PS)


def test_the_page_size_is_read_not_assumed():
    """Apple silicon uses 16 KB pages; assuming 4 KB is wrong by four times."""
    assert read(runner=RUNNER).page_size == 16384


def test_the_counters_are_parsed():
    stats = parse_vm_stat(VM_STAT)
    assert stats["pages free"] == 4153
    assert stats["swapins"] == 6341213


def test_swap_is_read_in_bytes():
    memory = read(runner=RUNNER)
    assert memory.swap_total == 2048 * (1 << 20)
    assert memory.swap_fraction == pytest.approx(0.823, abs=0.01)


def test_what_the_compressor_holds_is_not_what_it_swallowed():
    """Pages stored is cumulative; pages occupied is what it is holding now."""
    memory = read(runner=RUNNER)
    assert memory.compressed_bytes == 476028 * 16384


def test_a_machine_that_answers_nothing_does_not_crash():
    memory = read(runner=faker())
    assert memory.pressure == "green" and memory.processes == []


# ---------------------------------------------------------------- pressure


def test_plenty_of_room_is_green():
    assert Memory(free_percent=60, swap_total=GB, swap_used=0).pressure == "green"


def test_full_memory_on_its_own_is_still_green():
    """macOS fills RAM with cache on purpose. It is not a problem."""
    assert Memory(free_percent=35, swap_total=0, swap_used=0).pressure == "green"


def test_tight_memory_is_yellow():
    assert Memory(free_percent=15, swap_total=GB, swap_used=0).pressure == "yellow"


def test_a_nearly_full_swap_is_red_however_much_memory_looks_free():
    assert Memory(free_percent=60, swap_total=GB, swap_used=int(0.9 * GB)).pressure == "red"


def test_very_little_free_is_red():
    assert Memory(free_percent=5, swap_total=GB, swap_used=0).pressure == "red"


def test_every_level_explains_itself():
    for free, swap in ((60, 0), (15, 0), (5, 0)):
        assert Memory(free_percent=free, swap_total=GB, swap_used=swap).verdict


# --------------------------------------------------------------- processes


def test_helpers_are_added_to_the_app_they_belong_to():
    """Forty rows of "Helper (Renderer)" is not an answer."""
    found = {p.name: p for p in top_processes(runner=RUNNER)}
    assert found["Google Chrome"].rss == (432480 + 300448) * 1024
    assert found["Google Chrome"].count == 2


def test_something_outside_a_bundle_keeps_its_own_name():
    assert _app_name("/usr/sbin/cupsd") == "cupsd"


def test_processes_come_back_biggest_first():
    names = [p.name for p in top_processes(runner=RUNNER)]
    assert names[0] == "Google Chrome"


# ------------------------------------------------------------------ leaks


def series(values, *, start=0.0, step=3600.0):
    return [(start + i * step, v) for i, v in enumerate(values)]


def test_a_process_that_only_climbs_is_flagged():
    found = growth({"Leaky": series([GB + i * 200 * MB for i in range(8)])})
    assert [g.name for g in found] == ["Leaky"]


def test_an_app_you_simply_used_more_of_is_not():
    """A browser climbs all afternoon and gives it back when a tab closes."""
    sizes = [1 * GB, 2 * GB, 3 * GB, 4 * GB, 1 * GB, 2 * GB, 3 * GB, 4 * GB]
    assert growth({"Chrome": series(sizes)}) == []


def test_steady_use_is_not_a_leak():
    assert growth({"Steady": series([2 * GB] * 8)}) == []


def test_something_shrinking_is_not_a_leak():
    assert growth({"Tidy": series([8 * GB - i * GB for i in range(8)])}) == []


def test_too_few_readings_cannot_tell_a_trend_from_a_coincidence():
    assert growth({"Maybe": series([GB, 2 * GB, 3 * GB])}) == []


def test_growth_too_slow_to_matter_is_ignored():
    slow = [GB + i * (1 << 20) for i in range(10)]  # 1 MB an hour
    assert growth({"Slow": series(slow)}) == []


def test_the_rate_is_per_hour():
    found = growth({"Leaky": series([GB + i * 500 * MB for i in range(8)])})
    assert found[0].rate == pytest.approx(500 * MB, rel=0.01)


def test_the_worst_offender_comes_first():
    found = growth({
        "Fast": series([GB + i * 900 * MB for i in range(8)]),
        "Slower": series([GB + i * 100 * MB for i in range(8)]),
    })
    assert [g.name for g in found] == ["Fast", "Slower"]


def test_a_small_dip_does_not_excuse_a_leak():
    """Real processes wobble; the test is whether they ever truly retreat."""
    sizes = [GB + i * 300 * MB for i in range(8)]
    sizes[4] -= 20 * MB
    assert growth({"Leaky": series(sizes)})


def test_how_much_it_gained_is_reported():
    found = growth({"Leaky": series([GB + i * 500 * MB for i in range(8)])})
    assert found[0].gained == 7 * 500 * MB


def test_nothing_in_nothing_out():
    assert growth({}) == []
