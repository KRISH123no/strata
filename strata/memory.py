"""Memory, measured honestly.

The commonest Mac complaint is "my RAM is always full", and the commonest
product sold against it does not work. macOS fills idle memory with cache on
purpose: pages holding recently-read files stay resident because reading them
again is free, and the instant an app needs that memory the cache is dropped.
A tool that "frees" RAM forces the system to throw away a cache it was using
deliberately — the free-memory number rises and the next few minutes are
slower. That is not a bad implementation of a good idea.

So nothing here frees anything. What it does is **measure the things that
actually hurt**:

**Compression.** Since Mavericks macOS squeezes inactive pages rather than
writing them out. Compressing is cheap; doing it constantly is a symptom.

**Swap.** Once compression is not enough, pages go to disk. Swapping in and
out repeatedly — thrashing — is what a slow Mac actually feels like.

**A process that never gives memory back.** Normal use rises and falls. A
leak only rises. That is a shape you can detect, and it is the thing worth
knowing, because the fix is to quit one app rather than restart the machine.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .volume import run

Runner = Callable[[list[str]], str]

_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_STAT = re.compile(r'^"?([A-Za-z][^":]*)"?:\s+(\d+)', re.M)
_SWAP = re.compile(r"total = ([\d.]+)M\s+used = ([\d.]+)M\s+free = ([\d.]+)M")
_FREE_PCT = re.compile(r"free percentage:\s*(\d+)")

#: Below this share of memory free, macOS is working to keep up.
TIGHT = 20
#: And below this it is struggling.
CRITICAL = 10
#: Swap this full means the compressor has already given up.
SWAP_FULL = 0.75


@dataclass(slots=True)
class Process:
    name: str
    #: Resident set size in bytes, summed across every process of this name.
    rss: int
    count: int = 1


@dataclass(slots=True)
class Memory:
    """One reading of how the machine is coping."""

    page_size: int = 4096
    free_pages: int = 0
    wired_pages: int = 0
    compressed_pages: int = 0
    compressor_pages: int = 0
    compressions: int = 0
    decompressions: int = 0
    swapins: int = 0
    swapouts: int = 0
    swap_total: int = 0
    swap_used: int = 0
    free_percent: int = 0
    processes: list[Process] = field(default_factory=list)

    @property
    def swap_fraction(self) -> float:
        return self.swap_used / self.swap_total if self.swap_total else 0.0

    @property
    def compressed_bytes(self) -> int:
        """What the compressor is actually holding, not what it has swallowed."""
        return self.compressor_pages * self.page_size

    @property
    def pressure(self) -> str:
        """green, yellow or red — the number Activity Monitor shows and the
        one people ignore in favour of "memory used", which is always high and
        means nothing."""
        if self.free_percent and self.free_percent <= CRITICAL:
            return "red"
        if self.swap_fraction >= SWAP_FULL:
            return "red"
        if self.free_percent and self.free_percent <= TIGHT:
            return "yellow"
        if self.compressor_pages and self.swap_used:
            return "yellow"
        return "green"

    @property
    def verdict(self) -> str:
        return {
            "green": "coping — memory being full is how macOS is supposed to look",
            "yellow": "working to keep up: compressing, and starting to swap",
            "red": "struggling — swapping heavily, which is what slow feels like",
        }[self.pressure]


def parse_vm_stat(text: str) -> dict[str, int]:
    return {name.strip().lower(): int(value) for name, value in _STAT.findall(text)}


def read(*, runner: Runner = run) -> Memory:
    raw = runner(["vm_stat"])
    stats = parse_vm_stat(raw)
    page = _PAGE_SIZE.search(raw)

    memory = Memory(
        page_size=int(page.group(1)) if page else 4096,
        free_pages=stats.get("pages free", 0),
        wired_pages=stats.get("pages wired down", 0),
        compressed_pages=stats.get("pages stored in compressor", 0),
        compressor_pages=stats.get("pages occupied by compressor", 0),
        compressions=stats.get("compressions", 0),
        decompressions=stats.get("decompressions", 0),
        swapins=stats.get("swapins", 0),
        swapouts=stats.get("swapouts", 0),
    )

    swap = _SWAP.search(runner(["sysctl", "vm.swapusage"]))
    if swap:
        mb = 1 << 20
        memory.swap_total = int(float(swap.group(1)) * mb)
        memory.swap_used = int(float(swap.group(2)) * mb)

    free = _FREE_PCT.search(runner(["memory_pressure"]))
    if free:
        memory.free_percent = int(free.group(1))

    memory.processes = top_processes(runner=runner)
    return memory


def top_processes(*, limit: int = 12, runner: Runner = run) -> list[Process]:
    """Resident memory per application, not per process.

    A browser is forty processes with the same name. Forty rows of "Helper
    (Renderer)" is not an answer; the sum under one name is.
    """
    totals: dict[str, list[int]] = {}
    for line in runner(["ps", "-axo", "rss=,comm="]).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        kilobytes, command = int(parts[0]), parts[1]
        name = _app_name(command)
        bucket = totals.setdefault(name, [0, 0])
        bucket[0] += kilobytes * 1024
        bucket[1] += 1

    ranked = sorted(totals.items(), key=lambda item: -item[1][0])
    return [Process(name=n, rss=b[0], count=b[1]) for n, b in ranked[:limit]]


def _app_name(command: str) -> str:
    """`/Applications/Claude.app/Contents/.../Claude Helper` -> `Claude`.

    Helpers are named after their parent bundle so a browser's forty renderer
    processes add up to the browser rather than scattering.
    """
    for part in command.split("/"):
        if part.endswith(".app"):
            return part[:-4]
    return command.rsplit("/", 1)[-1]


@dataclass(slots=True)
class Growth:
    """A process that keeps taking memory and does not give it back."""

    name: str
    #: Bytes per hour, fitted across every reading.
    rate: float
    first: int
    last: int
    readings: int
    #: The largest fall from a running peak, as a share of that peak. A leak
    #: never really retreats; ordinary use does, constantly.
    retreat: float

    @property
    def gained(self) -> int:
        return self.last - self.first


#: Growth slower than this is noise on a machine someone is using.
MIN_RATE = 16 * 1024 * 1024  # bytes per hour
#: Give back more than this of your peak and you are not leaking, just busy.
MAX_RETREAT = 0.15
#: Fewer readings than this cannot tell a trend from a coincidence.
MIN_READINGS = 5


def growth(
    series: dict[str, list[tuple[float, int]]],
    *,
    min_rate: float = MIN_RATE,
    max_retreat: float = MAX_RETREAT,
    min_readings: int = MIN_READINGS,
) -> list[Growth]:
    """Find processes whose memory only ever goes up.

    Two conditions, and both matter. A **positive trend** alone catches any
    app you happen to have been using more of; a browser does that all
    afternoon and gives it all back when you close a tab. So it also has to
    have **never meaningfully retreated** — a leak has no reason to, because
    nothing is ever released. Measuring the largest drawdown from a running
    peak separates the two without needing to know anything about the app.
    """
    found: list[Growth] = []

    for name, readings in series.items():
        if len(readings) < min_readings:
            continue
        points = sorted(readings)
        hours = [t / 3600 for t, _ in points]
        sizes = [float(v) for _, v in points]

        rate = _slope(hours, sizes)
        if rate < min_rate:
            continue

        peak = sizes[0]
        retreat = 0.0
        for value in sizes:
            peak = max(peak, value)
            if peak:
                retreat = max(retreat, (peak - value) / peak)
        if retreat > max_retreat:
            continue

        found.append(
            Growth(name=name, rate=rate, first=int(sizes[0]), last=int(sizes[-1]),
                   readings=len(points), retreat=retreat)
        )

    return sorted(found, key=lambda item: -item.rate)


def _slope(xs: list[float], ys: list[float]) -> float:
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
