"""
YTMusic module for downloading and searching songs.
"""

import logging
from typing import Any, Dict, List

from rapidfuzz import fuzz
from ytmusicapi import YTMusic

from spotdl.providers.audio.base import ISRC_REGEX, AudioProvider
from spotdl.types.result import Result
from spotdl.types.song import Song
from spotdl.utils.formatter import create_search_query, parse_duration, slugify

__all__ = ["YouTubeMusic"]

logger = logging.getLogger(__name__)


class YouTubeMusic(AudioProvider):
    """
    YouTube Music audio provider class
    """

    SUPPORTS_ISRC = True
    SEARCH_ATTEMPTS = 3
    GET_RESULTS_OPTS: List[Dict[str, Any]] = [
        {"filter": "songs", "ignore_spelling": True, "limit": 50},
        {"filter": "videos", "ignore_spelling": True, "limit": 50},
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the YouTube Music API

        ### Arguments
        - args: Arguments passed to the `AudioProvider` class.
        - kwargs: Keyword arguments passed to the `AudioProvider` class.
        """

        super().__init__(*args, **kwargs)

        self.client = self._create_client()

    @staticmethod
    def _create_client() -> YTMusic:
        """
        Create a YTMusic API client.
        """

        try:
            return YTMusic(language="en", location="IN")
        except TypeError:
            return YTMusic(language="en", region="IN")

    def _score_result(self, song: Song, result: Result) -> float:
        """
        Score a YTMusic result by how closely it matches the requested song.
        """

        if result is None:
            return 0.0

        score = 0.0
        title = slugify(result.name or "")
        song_title = slugify(song.name or "")
        artist = slugify(result.author or "")
        song_artist = slugify(song.artist or "")
        album = slugify(result.album or "")
        song_album = slugify(song.album_name or "")

        if title == song_title:
            score += 70
        else:
            score += max(0.0, 0.7 * fuzz.ratio(title, song_title))

        if song_artist and song_artist in artist:
            score += 25
        elif artist and song_artist and fuzz.ratio(artist, song_artist) > 70:
            score += 20

        if song_album and album:
            if song_album in album or album in song_album:
                score += 15

        if result.verified:
            score += 10

        if result.duration and song.duration and abs(result.duration - song.duration) <= 15:
            score += 10

        return score

    def _get_search_templates(self, song: Song) -> List[str]:
        """
        Build a deterministic fallback order for YTMusic queries.

        We try the album/title combination first, then the plain title,
        then the composer/album-artist/title combination. This avoids the
        common case where the song title alone is too generic for regional
        or mixed-language tracks.
        """

        title = (song.name or "").strip()
        album = (song.album_name or "").strip()
        album_artist = (song.album_artist or "").strip()
        artist = (song.artist or "").strip()

        templates: List[str] = []
        if title and album and album.lower() not in title.lower():
            templates.append("{album} {title}")

        if title:
            templates.append("{title}")

        if title and album_artist and album_artist.lower() not in title.lower():
            templates.append("{album-artist} {title}")

        if title and artist and artist.lower() not in title.lower():
            templates.append("{artist} {title}")

        seen = set()
        ordered: List[str] = []
        for template in templates:
            if template in seen:
                continue
            seen.add(template)
            ordered.append(template)

        return ordered

    def search(self, song: Song, only_verified: bool = False) -> Any:
        """
        Search for a song with metadata-aware retries.

        We intentionally avoid the generic `AudioProvider.search()` matching
        pipeline because its fuzzy scoring can promote video-only cover clips
        over the actual song result.
        """

        original_search_query = self.search_query
        search_templates = self._get_search_templates(song)

        if self.search_query:
            search_templates.insert(0, self.search_query)

        try:
            for template in search_templates:
                self.search_query = template
                logger.info("[YTMusic] searching with query: %s", template)

                search_query = create_search_query(
                    song, self.search_query, False, None, True
                )
                best_result = None
                best_score = 0.0

                for options in (
                    {"filter": "songs", "ignore_spelling": True, "limit": 50},
                    {"filter": "videos", "ignore_spelling": True, "limit": 50},
                ):
                    search_results = self.get_results(search_query, **options)
                    if only_verified:
                        search_results = [
                            result for result in search_results if result.verified
                        ]

                    if not search_results:
                        continue

                    for result in search_results:
                        score = self._score_result(song, result)
                        if score > best_score:
                            best_result = result
                            best_score = score

                if best_result and best_score >= 80:
                    # Keep the original result URL instead of forcing the
                    # music.youtube.com domain. Some yt-dlp extractors and
                    # clients are more reliable with the standard
                    # youtube.com/watch?v=... URL while the music domain is
                    # only useful for search results and metadata.
                    result_url = best_result.url

                    logger.info("[YTMusic] selected result: %s", result_url)
                    return result_url
        finally:
            self.search_query = original_search_query

        return None

    def _get_search_terms(self, search_term: str) -> List[str]:
        """
        Build several search variants for mixed-language Indian playlists.
        """

        normalized = search_term.strip()
        variants = [
            normalized,
            f"{normalized} official",
            f"{normalized} full song",
            f"{normalized} lyrics",
        ]

        cleanup_replacements = {
            " - ": " ",
            " – ": " ",
            " — ": " ",
            "  ": " ",
        }
        clean_term = normalized
        for old, new in cleanup_replacements.items():
            clean_term = clean_term.replace(old, new).strip()

        if clean_term != normalized:
            variants.append(clean_term)
            variants.extend(
                [
                    f"{clean_term} official",
                    f"{clean_term} full song",
                    f"{clean_term} lyrics",
                ]
            )

        seen = set()
        ordered = []
        for term in variants:
            if not term or term in seen:
                continue
            seen.add(term)
            ordered.append(term)

        return ordered

    def get_results(
        self, search_term: str, log_search_failures: bool = True, **kwargs
    ) -> List[Result]:
        """
        Get results from YouTube Music API and simplify them

        ### Arguments
        - search_term: The search term to search for.
        - log_search_failures: Whether to log when a search returns no usable results.
        - kwargs: other keyword arguments passed to the `YTMusic.search` method.

        ### Returns
        - A list of simplified results (dicts)
        """

        is_isrc_result = ISRC_REGEX.search(search_term) is not None
        if is_isrc_result:
            kwargs["filter"] = "songs"
        # if is_isrc_result:
        #     print("FORCEFULLY SETTING FILTER TO SONGS")
        #     kwargs["filter"] = "songs"

        search_terms = self._get_search_terms(search_term)
        for index, search_term_variant in enumerate(search_terms, start=1):
            for attempt in range(self.SEARCH_ATTEMPTS):
                logger.info(
                    "[YTMusic] searching for %s (variant %s/%s, attempt %s/%s)",
                    search_term_variant,
                    index,
                    len(search_terms),
                    attempt + 1,
                    self.SEARCH_ATTEMPTS,
                )
                search_results = self.client.search(search_term_variant, **kwargs)

                # Simplify results
                results = []
                for result in search_results:
                    if (
                        result is None
                        or result.get("videoId") is None
                        or result.get("artists") in [[], None]
                    ):
                        continue

                    results.append(
                        Result(
                            source=self.name,
                            url=(
                                f'https://{"music" if result["resultType"] == "song" else "www"}'
                                f".youtube.com/watch?v={result['videoId']}"
                            ),
                            verified=result.get("resultType") == "song",
                            name=result["title"],
                            result_id=result["videoId"],
                            author=result["artists"][0]["name"],
                            artists=tuple(map(lambda a: a["name"], result["artists"])),
                            duration=parse_duration(result.get("duration")),
                            isrc_search=is_isrc_result,
                            search_query=search_term_variant,
                            explicit=result.get("isExplicit"),
                            album=(
                                result.get("album", {}).get("name")
                                if result.get("album")
                                else None
                            ),
                        )
                    )

                if results:
                    return results

                if attempt == self.SEARCH_ATTEMPTS - 1:
                    if not log_search_failures:
                        return []

                    logger.info(
                        "YouTube Music returned no usable results for %s after %s attempts",
                        search_term_variant,
                        self.SEARCH_ATTEMPTS,
                    )
                    continue

                if log_search_failures:
                    logger.debug(
                        "YouTube Music returned no usable results for %s on attempt %s/%s, "
                        "retrying with a new client",
                        search_term_variant,
                        attempt + 1,
                        self.SEARCH_ATTEMPTS,
                    )
                self.client = self._create_client()

            self.client = self._create_client()

        if log_search_failures:
            logger.info(
                "YouTube Music returned no usable results for %s after %s variants and %s attempts",
                search_term,
                len(self._get_search_terms(search_term)),
                self.SEARCH_ATTEMPTS,
            )

        return []
