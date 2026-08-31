import pytest

from spotdl.providers.audio import YouTubeMusic
from spotdl.types.result import Result
from spotdl.types.song import Song


@pytest.mark.vcr()
def test_ytm_search():
    provider = YouTubeMusic()

    assert (
        provider.search(
            Song.from_dict(
                {
                    "name": "Nobody Else",
                    "artists": ["Abstrakt"],
                    "artist": "Abstrakt",
                    "album_id": "0kx3ml8bdAYrQtcIwvkhp8",
                    "album_name": "Nobody Else",
                    "album_artist": "Abstrakt",
                    "album_type": "album",
                    "genres": [],
                    "disc_number": 1,
                    "disc_count": 1,
                    "duration": 162.406,
                    "year": 2022,
                    "date": "2022-03-17",
                    "track_number": 1,
                    "tracks_count": 1,
                    "isrc": "GB2LD2210007",
                    "song_id": "0kx3ml8bdAYrQtcIwvkhp8",
                    "cover_url": "https://i.scdn.co/image/ab67616d0000b27345f5ba253b9825efc88bc236",
                    "explicit": False,
                    "publisher": "NCS",
                    "url": "https://open.spotify.com/track/0kx3ml8bdAYrQtcIwvkhp8",
                    "copyright_text": "2022 NCS",
                    "download_url": None,
                }
            )
        )
        is not None
    )


@pytest.mark.vcr()
def test_ytm_get_results():
    provider = YouTubeMusic()

    results = provider.get_results("Lost Identities Moments")

    assert len(results) > 3


def test_ytm_get_results_retries_with_new_client(mocker):
    first_client = mocker.Mock()
    first_client.search.return_value = []
    second_client = mocker.Mock()
    second_client.search.return_value = [
        {
            "videoId": "video_0",
            "resultType": "song",
            "title": "Test Song",
            "artists": [{"name": "Test Artist"}],
            "duration": "1:23",
        }
    ]
    mocker.patch(
        "spotdl.providers.audio.ytmusic.YTMusic",
        side_effect=[first_client, second_client],
    )

    provider = YouTubeMusic()
    results = provider.get_results("Test Song")

    assert len(results) == 1
    assert results[0].url == "https://music.youtube.com/watch?v=video_0"
    assert results[0].name == "Test Song"
    assert first_client.search.call_count == 1
    assert second_client.search.call_count == 1


def test_normalize_youtube_music_url():
    assert (
        YouTubeMusic.normalize_youtube_url(
            "https://music.youtube.com/watch?v=abc123&list=PL123"
        )
        == "https://music.youtube.com/watch?v=abc123&list=PL123"
    )
    assert (
        YouTubeMusic.normalize_youtube_url("https://m.youtube.com/watch?v=abc123")
        == "https://music.youtube.com/watch?v=abc123"
    )


def test_ytm_search_templates_retry_in_order():
    song = Song.from_dict(
        {
            "name": "Maate Vinadhuga",
            "artists": ["Jakes Bejoy"],
            "artist": "Jakes Bejoy",
            "album_id": "album_123",
            "album_name": "Aabharana",
            "album_artist": "Jakes Bejoy",
            "album_type": "album",
            "genres": [],
            "disc_number": 1,
            "disc_count": 1,
            "duration": 180,
            "year": 2024,
            "date": "2024-01-01",
            "track_number": 1,
            "tracks_count": 1,
            "isrc": "INABC1234567",
            "song_id": "song_123",
            "cover_url": "https://example.com/cover.jpg",
            "explicit": False,
            "publisher": "Test Publisher",
            "url": "https://open.spotify.com/track/song_123",
            "copyright_text": "2024 Test",
        }
    )

    templates = YouTubeMusic()._get_search_templates(song)

    assert templates[0] == "{album} {title}"
    assert templates[1] == "{title}"
    assert templates[2] == "{album-artist} {title}"
    assert templates[3] == "{artist} {title}"


def test_ytm_search_prefers_song_results_over_video_results(mocker):
    provider = YouTubeMusic()
    song = Song.from_dict(
        {
            "name": "Oye Meghamla",
            "artists": ["Chinmayi Sripada"],
            "artist": "Chinmayi Sripada",
            "album_id": "album_456",
            "album_name": "Majnu",
            "album_artist": "Chinmayi Sripada",
            "album_type": "album",
            "genres": [],
            "disc_number": 1,
            "disc_count": 1,
            "duration": 240,
            "year": 2016,
            "date": "2016-01-01",
            "track_number": 1,
            "tracks_count": 1,
            "isrc": "INABC7654321",
            "song_id": "song_456",
            "cover_url": "https://example.com/cover2.jpg",
            "explicit": False,
            "publisher": "Test Publisher",
            "url": "https://open.spotify.com/track/song_456",
            "copyright_text": "2016 Test",
        }
    )

    song_result = Result(
        source="youtube-music",
        url="https://www.youtube.com/watch?v=good_video",
        verified=True,
        name="Oye Meghamla",
        duration=240,
        author="Chinmayi Sripada",
        result_id="good_video",
        artists=("Chinmayi Sripada",),
    )
    video_result = Result(
        source="youtube-music",
        url="https://www.youtube.com/watch?v=bad_video",
        verified=False,
        name="Oye Meghamla",
        duration=240,
        author="Chinmayi Sripada",
        result_id="bad_video",
        artists=("Chinmayi Sripada",),
    )

    mocker.patch.object(
        provider,
        "get_results",
        side_effect=[
            [song_result],
            [video_result],
        ],
    )

    result = provider.search(song)

    assert result == "https://www.youtube.com/watch?v=good_video"
