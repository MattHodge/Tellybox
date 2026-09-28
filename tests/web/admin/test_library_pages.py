"""Library admin pages (CI-4, CI-6, LM-1..LM-4): /admin/library, /admin/shows/{id},
/admin/episodes/... and the /admin/img/... routes.

Uses the seeded `lib` fixture (tests/web/conftest.py):
  Bravo (sort 0, has artwork): b1, b2, b3
  Alpha (sort 1, no artwork): a1, a2, a3 (hidden), a4
  Hidden (hidden show): h1
  Empty (only a hidden episode): e1
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tellybox import db, library

pytestmark_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args], check=True)


@pytest.fixture(scope="session")
def jpeg_bytes(tmp_path_factory) -> bytes:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not installed")
    out = tmp_path_factory.mktemp("lib-pages") / "a.jpg"
    _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(out))
    return out.read_bytes()


def _write_episode_video(admin_env, rel_path: str, seconds: int = 2) -> None:
    path = admin_env.config.media_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=5:duration={seconds}",
        "-c:v", "libx264", "-preset", "superfast", "-pix_fmt", "yuv420p", str(path),
    )


def _hold(conn, youtube_id: str, *, show_id=None, status="ready", with_episode=True, hidden=True):
    """A held (publish='hold') source video, matching what ingest._publish produces."""
    from tests.web.conftest import NOW

    cur = conn.execute(
        """INSERT INTO source_video (youtube_id, url, title, show_id, file_path, publish, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'hold', ?, ?, ?)""",
        (youtube_id, f"https://youtu.be/{youtube_id}", f"Title {youtube_id}", show_id, None, status,
         db.to_db(NOW), db.to_db(NOW)),
    )
    source_id = cur.lastrowid
    episode_id = None
    if with_episode and show_id is not None:
        episode_id = library.add_episode(
            conn, show_id, f"Title {youtube_id}", f"held/{youtube_id}.mp4", now=NOW,
            source_video_id=source_id, hidden=hidden,
        )
    return source_id, episode_id


# --------------------------------------------------------------------------- library page


def test_library_page_renders(admin, admin_env):
    r = admin.get("/admin/library")
    assert r.status_code == 200
    assert "Bravo" in r.text
    assert "Alpha" in r.text
    assert "Hidden" in r.text


def test_library_page_shows_held_downloads(admin, admin_env):
    _hold(admin_env.conn, "held1", show_id=admin_env.ids.alpha, status="ready")
    r = admin.get("/admin/library")
    assert r.status_code == 200
    assert "Title held1" in r.text


def test_create_show(admin, admin_env):
    r = admin.post("/admin/shows", data={"name": "New Show"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/library"
    names = [row["name"] for row in admin_env.conn.execute("SELECT name FROM show")]
    assert "New Show" in names


def test_create_show_empty_name_is_422(admin, admin_env):
    r = admin.post("/admin/shows", data={"name": "   "}, follow_redirects=False)
    assert r.status_code == 422
    assert "empty" in r.text.lower()


def test_merge_shows_via_page(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(
        "/admin/shows/merge", data={"into_id": ids.bravo, "from_id": ids.alpha, "confirm": "yes"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert library.get_show(admin_env.conn, ids.alpha) is None
    moved = library.list_episodes(admin_env.conn, ids.bravo, include_hidden=True)
    assert ids.a1 in [e.id for e in moved]


def test_merge_shows_without_confirm_is_422(admin, admin_env):
    ids = admin_env.ids
    r = admin.post("/admin/shows/merge", data={"into_id": ids.bravo, "from_id": ids.alpha}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_show(admin_env.conn, ids.alpha) is not None


def test_merge_show_into_itself_is_422(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(
        "/admin/shows/merge", data={"into_id": ids.bravo, "from_id": ids.bravo, "confirm": "yes"},
        follow_redirects=False,
    )
    assert r.status_code == 422


def test_merge_unknown_show_is_404(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(
        "/admin/shows/merge", data={"into_id": ids.bravo, "from_id": 999999, "confirm": "yes"},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_publish_held_download(admin, admin_env):
    source_id, episode_id = _hold(admin_env.conn, "held2", show_id=admin_env.ids.alpha, status="ready")
    r = admin.post(f"/admin/held/{source_id}/publish", follow_redirects=False)
    assert r.status_code == 303
    assert library.get_episode(admin_env.conn, episode_id).hidden is False
    row = admin_env.conn.execute("SELECT publish FROM source_video WHERE id = ?", (source_id,)).fetchone()
    assert row["publish"] == "publish"


def test_publish_held_unknown_is_404(admin):
    r = admin.post("/admin/held/999999/publish", follow_redirects=False)
    assert r.status_code == 404


# --------------------------------------------------------------------------- held playlists (CI-7)


def _hold_in_playlist(conn, youtube_id: str, playlist_id: str, playlist_title: str, *, show_id, status="ready",
                      with_episode=True):
    source_id, episode_id = _hold(conn, youtube_id, show_id=show_id, status=status, with_episode=with_episode)
    conn.execute("UPDATE source_video SET playlist_id = ?, playlist_title = ? WHERE id = ?",
                 (playlist_id, playlist_title, source_id))
    return source_id, episode_id


def test_group_held_splits_playlists_from_single_videos():
    from tellybox.web.admin.library_pages import group_held

    def held(sid, playlist_id=None, status="ready", episode_id=1):
        return library.HeldDownload(source_id=sid, title=f"T{sid}", status=status, error=None, episode_id=episode_id,
                                    thumbnail_path=None, playlist_id=playlist_id,
                                    playlist_title=f"List {playlist_id}" if playlist_id else None)

    single, groups = group_held([
        held(1), held(2, "PLa"), held(3, "PLb"), held(4, "PLa", status="downloading", episode_id=None), held(5),
    ])
    assert [h.source_id for h in single] == [1, 5]
    assert [(g["playlist_id"], g["title"], [h.source_id for h in g["items"]], g["ready"]) for g in groups] == [
        ("PLa", "List PLa", [2, 4], 1),
        ("PLb", "List PLb", [3], 1),
    ]


def test_library_groups_held_playlist_videos(admin, admin_env):
    conn, alpha = admin_env.conn, admin_env.ids.alpha
    _hold(conn, "single1", show_id=alpha)
    _hold_in_playlist(conn, "pl1", "PLkids_1-x", "Nursery <b>Rhymes</b>", show_id=alpha)
    _hold_in_playlist(conn, "pl2", "PLkids_1-x", "Nursery <b>Rhymes</b>", show_id=alpha, status="downloading",
                      with_episode=False)
    r = admin.get("/admin/library")
    assert r.status_code == 200
    assert "Nursery &lt;b&gt;Rhymes&lt;/b&gt;" in r.text
    assert "1 of 2 ready" in r.text
    assert 'action="/admin/held/playlist/PLkids_1-x/publish"' in r.text
    assert "Publish all ready" in r.text
    assert "Title single1" in r.text and "Title pl1" in r.text and "Title pl2" in r.text
    # per-video publish stays
    assert r.text.count('action="/admin/held/') == 4


def test_publish_all_ready_in_held_playlist(admin, admin_env):
    conn, alpha = admin_env.conn, admin_env.ids.alpha
    s1, e1 = _hold_in_playlist(conn, "pl1", "PLkids", "Nursery", show_id=alpha)
    s2, e2 = _hold_in_playlist(conn, "pl2", "PLkids", "Nursery", show_id=alpha)
    s3, _ = _hold_in_playlist(conn, "pl3", "PLkids", "Nursery", show_id=alpha, status="downloading",
                              with_episode=False)
    other, e_other = _hold_in_playlist(conn, "zz1", "PLother", "Other", show_id=alpha)
    r = admin.post("/admin/held/playlist/PLkids/publish", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/library"
    assert library.get_episode(conn, e1).hidden is False
    assert library.get_episode(conn, e2).hidden is False
    assert library.get_episode(conn, e_other).hidden is True
    publish = dict(conn.execute("SELECT id, publish FROM source_video").fetchall())
    assert (publish[s1], publish[s2], publish[s3], publish[other]) == ("publish", "publish", "hold", "hold")
    assert "Published 2 videos to the kid app." in admin.get("/admin/library").text


def test_publish_all_ready_unknown_playlist_is_404(admin):
    r = admin.post("/admin/held/playlist/PLnothing/publish", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.parametrize("bad", ["PL%20x", "PL.x", "PL%3Cscript%3E"])
def test_publish_all_ready_rejects_malformed_playlist_id(admin, bad):
    r = admin.post(f"/admin/held/playlist/{bad}/publish", follow_redirects=False)
    assert r.status_code == 404


def test_publish_all_ready_refuses_cross_origin(admin, admin_env):
    _, e1 = _hold_in_playlist(admin_env.conn, "pl1", "PLkids", "Nursery", show_id=admin_env.ids.alpha)
    r = admin.post("/admin/held/playlist/PLkids/publish", headers={"Origin": "http://evil.example"},
                   follow_redirects=False)
    assert r.status_code == 403
    assert library.get_episode(admin_env.conn, e1).hidden is True


# --------------------------------------------------------------------------- show page


def test_show_page_renders(admin, admin_env):
    r = admin.get(f"/admin/shows/{admin_env.ids.bravo}")
    assert r.status_code == 200
    assert "Bravo" in r.text
    assert "Title b1" in r.text


def test_show_page_shows_hidden_episodes(admin, admin_env):
    r = admin.get(f"/admin/shows/{admin_env.ids.alpha}")
    assert r.status_code == 200
    assert "Title a3" in r.text  # hidden, but the admin still sees it


def test_show_page_unknown_is_404(admin):
    assert admin.get("/admin/shows/999999").status_code == 404


def test_rename_show(admin, admin_env):
    show_id = admin_env.ids.bravo
    r = admin.post(f"/admin/shows/{show_id}/rename", data={"name": "  Bravo Renamed  "}, follow_redirects=False)
    assert r.status_code == 303
    assert library.get_show(admin_env.conn, show_id).name == "Bravo Renamed"


def test_rename_show_empty_is_422(admin, admin_env):
    show_id = admin_env.ids.bravo
    r = admin.post(f"/admin/shows/{show_id}/rename", data={"name": "   "}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_show(admin_env.conn, show_id).name == "Bravo"


def test_rename_show_unknown_is_404(admin):
    r = admin.post("/admin/shows/999999/rename", data={"name": "x"}, follow_redirects=False)
    assert r.status_code == 404


def test_toggle_autoplay(admin, admin_env):
    show_id = admin_env.ids.bravo
    before = library.get_show(admin_env.conn, show_id).autoplay
    r = admin.post(f"/admin/shows/{show_id}/autoplay", data={"autoplay": "0" if before else "1"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert library.get_show(admin_env.conn, show_id).autoplay is not before


def test_toggle_show_hidden(admin, admin_env):
    show_id = admin_env.ids.bravo
    r = admin.post(f"/admin/shows/{show_id}/hidden", data={"hidden": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert library.get_show(admin_env.conn, show_id).hidden is True
    r = admin.post(f"/admin/shows/{show_id}/hidden", data={"hidden": "0"}, follow_redirects=False)
    assert library.get_show(admin_env.conn, show_id).hidden is False


def test_delete_show_requires_typed_name(admin, admin_env):
    show_id = admin_env.ids.bravo
    r = admin.post(f"/admin/shows/{show_id}/delete", data={"confirm_name": "wrong"}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_show(admin_env.conn, show_id) is not None


def test_delete_show(admin, admin_env):
    show_id = admin_env.ids.empty  # no real files, simplest to delete
    r = admin.post(f"/admin/shows/{show_id}/delete", data={"confirm_name": "Empty"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/library"
    assert library.get_show(admin_env.conn, show_id) is None


def test_delete_show_unknown_is_404(admin):
    r = admin.post("/admin/shows/999999/delete", data={"confirm_name": "x"}, follow_redirects=False)
    assert r.status_code == 404


# --------------------------------------------------------------------------- episodes


def test_rename_episode(admin, admin_env):
    episode_id = admin_env.ids.b1
    r = admin.post(f"/admin/episodes/{episode_id}/rename", data={"title": "  New title  "}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/shows/{admin_env.ids.bravo}"
    assert library.get_episode(admin_env.conn, episode_id).title == "New title"


def test_rename_episode_empty_is_422(admin, admin_env):
    episode_id = admin_env.ids.b1
    r = admin.post(f"/admin/episodes/{episode_id}/rename", data={"title": "   "}, follow_redirects=False)
    assert r.status_code == 422


def test_rename_episode_unknown_is_404(admin):
    r = admin.post("/admin/episodes/999999/rename", data={"title": "x"}, follow_redirects=False)
    assert r.status_code == 404


def test_toggle_episode_hidden(admin, admin_env):
    episode_id = admin_env.ids.b1
    r = admin.post(f"/admin/episodes/{episode_id}/hidden", data={"hidden": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert library.get_episode(admin_env.conn, episode_id).hidden is True


def test_move_episode(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(f"/admin/episodes/{ids.b1}/move", data={"to_show_id": ids.alpha}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/shows/{ids.alpha}"
    assert library.get_episode(admin_env.conn, ids.b1).show_id == ids.alpha


def test_move_episode_unknown_target_is_422(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(f"/admin/episodes/{ids.b1}/move", data={"to_show_id": 999999}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_episode(admin_env.conn, ids.b1).show_id == ids.bravo


def test_move_episode_unknown_episode_is_404(admin, admin_env):
    r = admin.post("/admin/episodes/999999/move", data={"to_show_id": admin_env.ids.alpha}, follow_redirects=False)
    assert r.status_code == 404


def test_move_episode_step(admin, admin_env):
    ids = admin_env.ids
    before = [e.id for e in library.list_episodes(admin_env.conn, ids.bravo)]
    r = admin.post(f"/admin/episodes/{ids.b2}/move-step", data={"direction": "up"}, follow_redirects=False)
    assert r.status_code == 303
    after = [e.id for e in library.list_episodes(admin_env.conn, ids.bravo)]
    assert after != before
    assert after[0] == ids.b2


def test_move_episode_step_bad_direction_is_422(admin, admin_env):
    r = admin.post(f"/admin/episodes/{admin_env.ids.b1}/move-step", data={"direction": "sideways"},
                   follow_redirects=False)
    assert r.status_code == 422


def test_delete_episode_requires_typed_confirmation(admin, admin_env):
    episode_id = admin_env.ids.b3  # duration_s=None, no thumbnail file to worry about
    r = admin.post(f"/admin/episodes/{episode_id}/delete", data={"confirm": "no"}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_episode(admin_env.conn, episode_id) is not None


def test_delete_episode(admin, admin_env):
    episode_id = admin_env.ids.b3
    r = admin.post(f"/admin/episodes/{episode_id}/delete", data={"confirm": "DELETE"}, follow_redirects=False)
    assert r.status_code == 303
    assert library.get_episode(admin_env.conn, episode_id) is None


def test_delete_episode_unknown_is_404(admin):
    r = admin.post("/admin/episodes/999999/delete", data={"confirm": "delete"}, follow_redirects=False)
    assert r.status_code == 404


# --------------------------------------------------------------------------- images


def test_show_image_serves_artwork(admin, admin_env):
    r = admin.get(f"/admin/img/show/{admin_env.ids.bravo}.jpg")
    assert r.status_code == 200


def test_show_image_falls_back_to_episode_thumbnail(admin, admin_env):
    # Alpha has no artwork; falls back to its first episode's thumbnail.
    r = admin.get(f"/admin/img/show/{admin_env.ids.alpha}.jpg")
    assert r.status_code == 200


def test_show_image_unknown_is_404(admin):
    assert admin.get("/admin/img/show/999999.jpg").status_code == 404


def test_episode_image_serves_thumbnail(admin, admin_env):
    r = admin.get(f"/admin/img/episode/{admin_env.ids.b1}.jpg")
    assert r.status_code == 200


def test_episode_image_hidden_still_served(admin, admin_env):
    # a3 is hidden; admin image serving includes hidden items, unlike the kid app.
    r = admin.get(f"/admin/img/episode/{admin_env.ids.a3}.jpg")
    assert r.status_code == 200


def test_episode_image_unknown_is_404(admin):
    assert admin.get("/admin/img/episode/999999.jpg").status_code == 404


# --------------------------------------------------------------------------- artwork / thumbnail uploads


@pytestmark_ffmpeg
def test_upload_show_artwork(admin, admin_env, jpeg_bytes):
    show_id = admin_env.ids.bravo
    before = library.get_show(admin_env.conn, show_id).artwork_path
    r = admin.post(f"/admin/shows/{show_id}/artwork/upload", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")},
                   follow_redirects=False)
    assert r.status_code == 303
    after = library.get_show(admin_env.conn, show_id).artwork_path
    assert after != before
    assert (admin_env.config.media_dir / after).exists()
    if before:
        assert not (admin_env.config.media_dir / before).exists()


@pytestmark_ffmpeg
def test_upload_show_artwork_rejects_non_image(admin, admin_env):
    show_id = admin_env.ids.bravo
    before = library.get_show(admin_env.conn, show_id).artwork_path
    r = admin.post(f"/admin/shows/{show_id}/artwork/upload",
                   files={"file": ("a.txt", b"not an image", "text/plain")}, follow_redirects=False)
    assert r.status_code == 422
    assert library.get_show(admin_env.conn, show_id).artwork_path == before


@pytestmark_ffmpeg
def test_upload_show_artwork_unknown_show_is_404(admin, jpeg_bytes):
    r = admin.post("/admin/shows/999999/artwork/upload", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")},
                   follow_redirects=False)
    assert r.status_code == 404


@pytestmark_ffmpeg
def test_upload_episode_thumbnail(admin, admin_env, jpeg_bytes):
    episode_id = admin_env.ids.a1
    before = library.get_episode(admin_env.conn, episode_id).thumbnail_path
    r = admin.post(f"/admin/episodes/{episode_id}/thumbnail/upload",
                   files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303
    after = library.get_episode(admin_env.conn, episode_id).thumbnail_path
    assert after != before
    assert (admin_env.config.media_dir / after).exists()


@pytestmark_ffmpeg
def test_upload_episode_thumbnail_unknown_is_404(admin, jpeg_bytes):
    r = admin.post("/admin/episodes/999999/thumbnail/upload", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")},
                   follow_redirects=False)
    assert r.status_code == 404


# --------------------------------------------------------------------------- frame picking


@pytestmark_ffmpeg
def test_frame_preview(admin, admin_env):
    ids = admin_env.ids
    _write_episode_video(admin_env, "eps/b1.mp4")
    r = admin.get(f"/admin/episodes/{ids.b1}/frame.jpg?t=1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store"


@pytestmark_ffmpeg
def test_frame_preview_past_the_end_still_returns_a_frame(admin, admin_env):
    ids = admin_env.ids
    _write_episode_video(admin_env, "eps/b1.mp4")
    r = admin.get(f"/admin/episodes/{ids.b1}/frame.jpg?t=999")
    assert r.status_code == 200


@pytestmark_ffmpeg
def test_frame_preview_unknown_episode_is_404(admin):
    assert admin.get("/admin/episodes/999999/frame.jpg?t=1").status_code == 404


@pytestmark_ffmpeg
def test_use_episode_thumbnail_frame(admin, admin_env):
    ids = admin_env.ids
    _write_episode_video(admin_env, "eps/b1.mp4")
    before = library.get_episode(admin_env.conn, ids.b1).thumbnail_path
    r = admin.post(f"/admin/episodes/{ids.b1}/thumbnail/frame", data={"t": "1"}, follow_redirects=False)
    assert r.status_code == 303
    after = library.get_episode(admin_env.conn, ids.b1).thumbnail_path
    assert after != before
    assert (admin_env.config.media_dir / after).exists()


@pytestmark_ffmpeg
def test_use_show_artwork_frame(admin, admin_env):
    ids = admin_env.ids
    _write_episode_video(admin_env, "eps/b1.mp4")
    before = library.get_show(admin_env.conn, ids.bravo).artwork_path
    r = admin.post(f"/admin/shows/{ids.bravo}/artwork/frame", data={"episode_id": ids.b1, "t": "1"},
                   follow_redirects=False)
    assert r.status_code == 303
    after = library.get_show(admin_env.conn, ids.bravo).artwork_path
    assert after != before
    assert (admin_env.config.media_dir / after).exists()


@pytestmark_ffmpeg
def test_use_show_artwork_frame_rejects_episode_of_another_show(admin, admin_env):
    ids = admin_env.ids
    r = admin.post(f"/admin/shows/{ids.bravo}/artwork/frame", data={"episode_id": ids.a1, "t": "1"},
                   follow_redirects=False)
    assert r.status_code == 422
