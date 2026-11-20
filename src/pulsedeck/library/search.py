# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Search helpers for the library and playlists.

Query syntax: free words match title, artist, album or genre; ``field:value``
restricts a term (``artist:nina``, ``album:"blue train"``, ``genre:jazz``,
``year:1999``).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from pulsedeck.core.database import LibraryDatabase
from pulsedeck.library.models import TrackInfo

SEARCH_FIELDS = ("title", "artist", "album", "genre")
FIELD_ALIASES = {
    "title": "title", "song": "title", "artist": "artist", "by": "artist",
    "album": "album", "genre": "genre", "year": "year", "albumartist": "album_artist",
    "composer": "composer",
}


@dataclass
class SearchQuery:
    words: list[str] = field(default_factory=list)
    fielded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.words and not self.fielded


def parse_query(text: str) -> SearchQuery:
    query = SearchQuery()
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for token in tokens:
        name, sep, value = token.partition(":")
        if sep and name.lower() in FIELD_ALIASES and value:
            query.fielded.append((FIELD_ALIASES[name.lower()], value))
        elif token:
            query.words.append(token)
    return query


def matches(info: TrackInfo, query: SearchQuery | str) -> bool:
    if isinstance(query, str):
        query = parse_query(query)
    haystack = " ".join(str(getattr(info, f) or "") for f in SEARCH_FIELDS).casefold()
    haystack += " " + info.display_title.casefold()
    for word in query.words:
        if word.casefold() not in haystack:
            return False
    return all(value.casefold() in str(getattr(info, name, "") or "").casefold() for name, value in query.fielded)


def search_library(db: LibraryDatabase, text: str, scope: str = "all", **filters: str | None) -> list[TrackInfo]:
    """Search the library; ``scope`` limits free words to one field."""
    query = parse_query(text)
    fields = SEARCH_FIELDS if scope == "all" else (scope,)
    candidates = db.query_tracks(" ".join(query.words), fields_=tuple(fields), **filters)  # type: ignore[arg-type]
    if query.fielded:
        candidates = [t for t in candidates if matches(t, SearchQuery([], query.fielded))]
    return candidates
