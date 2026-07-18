"""Token counting for the session explorer.

Two functions, kept distinct on purpose:

* :func:`count_tokens` — real BPE via tiktoken's ``o200k_base`` (GPT-4o vocabulary),
  a tight approximation of Claude usage. Reserve it for offline passes where accuracy
  matters (the export roll-up).
* :func:`estimate_tokens` — a cheap, deterministic ~4-chars/token heuristic for the
  per-event replay hot path. Not tiktoken: fast, and its figures stay stable.

Neither is a billed figure; call the API at emit time for that.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken

_TIKTOKEN_ENCODING = "o200k_base"


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_TIKTOKEN_ENCODING)


def count_tokens(text: str) -> int:
    """A string's tokens via a real BPE tokenizer (GPT-4o vocabulary).

    Special-token markers in ``text`` are counted as ordinary text.
    """
    return len(_encoder().encode(text, disallowed_special=()))


def estimate_tokens(text: str) -> int:
    """A cheap, deterministic token estimate: ~4 chars/token with a word-count floor."""
    return max(len(text) // 4, len(text.split()))
