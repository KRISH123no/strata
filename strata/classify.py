"""What a directory is, and whether its bytes are yours or the machine's.

Three kinds, and the distinction is the whole point of the tool:

**Reclaimable** — a cache. Deleting it costs time, not data. It will come
back on its own.

**Managed** — an application's own store. It can usually be emptied, but from
inside the app, not with `rm`. Prime Video downloads, Spotify's offline songs,
Photos. Deleting the directory under the app's feet corrupts its database.

**Yours** — documents, code, pictures. Never suggested, under any
circumstances.

And a fourth category that overrides all of them: **off-limits**. Some caches
are rebuilt only at enormous cost, or are load-bearing for work in progress.
Those are reported and never recommended, however large they get.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RECLAIMABLE = "reclaimable"
MANAGED = "managed"
YOURS = "yours"
OFF_LIMITS = "off-limits"


@dataclass(slots=True)
class Verdict:
    kind: str
    why: str
    #: What to run, when there is a safe way to do it. Printed, never executed.
    command: str = ""


#: Order matters: the first rule that matches wins, so the narrow exceptions
#: have to come before the broad "anything called Caches" rule.
RULES: list[tuple[re.Pattern[str], Verdict]] = [
    (
        re.compile(r"/\.cache/uv(/|$)"),
        Verdict(OFF_LIMITS, "uv's package cache — rebuilding it re-downloads every wheel",
                "uv cache prune   # removes only what nothing references"),
    ),
    (
        re.compile(r"/\.(npm|cargo|rustup|gradle|m2|pub-cache)(/|$)"),
        Verdict(OFF_LIMITS, "a package manager's cache — expensive to rebuild",
                "npm cache verify   # or the equivalent for this tool"),
    ),
    (
        re.compile(r"/\.cache/huggingface(/|$)"),
        Verdict(MANAGED, "downloaded model weights — gigabytes each, and slow to fetch again",
                "huggingface-cli delete-cache"),
    ),
    (
        re.compile(r"/Library/Developer/(Xcode/DerivedData|CoreSimulator)(/|$)"),
        Verdict(RECLAIMABLE, "Xcode build products and simulator images, rebuilt on demand"),
    ),
    (
        re.compile(r"/Library/Containers/com\.amazon\.aiv\.AIVApp(/|$)"),
        Verdict(MANAGED, "Prime Video downloads — invisible in Finder, and often the largest "
                         "single thing on the disk",
                "Prime Video → Downloads → remove watched titles"),
    ),
    (
        re.compile(r"/Library/Application Support/Spotify/PersistentCache(/|$)"),
        Verdict(MANAGED, "Spotify's offline songs and cache",
                "Spotify → Settings → Storage → Clear cache"),
    ),
    (
        re.compile(r"/Library/(Application Support|Containers)/[^/]*(Chrome|Firefox|Safari|Arc)"),
        Verdict(MANAGED, "a browser profile — history, logins and cache together",
                "the browser's own Clear Browsing Data"),
    ),
    (
        re.compile(r"/Library/Containers/com\.apple\.(Photos|photo)"),
        Verdict(YOURS, "your photo library"),
    ),
    (
        re.compile(r"(^|/)(Movies|Music|Pictures|Documents|Desktop|Downloads)(/|$)"),
        Verdict(YOURS, "your own files"),
    ),
    (
        re.compile(r"/(Caches|CachedData|\.cache|Cache)(/|$)", re.IGNORECASE),
        Verdict(RECLAIMABLE, "a cache — deleting it costs time, not data"),
    ),
    (
        re.compile(r"/(node_modules|\.venv|venv|target|build|dist|__pycache__)(/|$)"),
        Verdict(RECLAIMABLE, "build output, rebuilt from source"),
    ),
    (
        re.compile(r"/Library/(Application Support|Containers|Group Containers)(/|$)"),
        Verdict(MANAGED, "an application's own store — empty it from inside the app"),
    ),
]

UNKNOWN = Verdict("unknown", "not recognised — look before you touch it")


def classify(path: str) -> Verdict:
    for pattern, verdict in RULES:
        if pattern.search(path):
            return verdict
    return UNKNOWN


def safe_to_suggest(path: str) -> bool:
    """Only ever caches and build output, and never the protected ones."""
    return classify(path).kind == RECLAIMABLE
