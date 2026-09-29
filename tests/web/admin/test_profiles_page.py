"""Admin `/admin/profiles` (step 8, PR-1): list, add, edit, reorder, photos, delete guards."""

from __future__ import annotations

import pytest

from tellybox.avatars import AVATARS

from tests.web.admin.test_library_pages import jpeg_bytes, pytestmark_ffmpeg  # noqa: F401  (fixture + marker)
from tests.web.conftest import PROFILE

XSS = '<script>alert("x")</script>'


def rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM profile ORDER BY sort_order, id")]


def add(admin, name="Noor", avatar="owl", **kw):
    return admin.post("/admin/profiles", data={"name": name, "avatar": avatar}, follow_redirects=False, **kw)


def watching(admin_env, *ids):
    from tests.web.conftest import playing
    admin_env.cast.current = admin_env.cast.current | {
        "now_playing": playing(admin_env.ids.b1, admin_env.ids.bravo, profile_ids=list(ids))}


# --------------------------------------------------------------------------- list


def test_page_lists_profiles_with_avatar_and_photo(admin, admin_env):
    conn = admin_env.conn
    conn.execute("UPDATE profile SET name = 'Mila', avatar = 'fox' WHERE id = 1")
    conn.execute("INSERT INTO profile (id, name, picture_path, sort_order, created_at) VALUES (2, 'Sam', 'profiles/s.jpg', 2, 'x')")
    r = admin.get("/admin/profiles")
    assert r.status_code == 200
    assert "Mila" in r.text and "Sam" in r.text
    assert "/static/avatars/fox.svg" in r.text
    assert "/img/profile/2.jpg" in r.text


def test_page_is_in_the_nav(admin):
    assert 'href="/admin/profiles"' in admin.get("/admin").text


def test_page_needs_sign_in(anon):
    r = anon.get("/admin/profiles", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/login")


def test_page_renders_with_cast_down(admin, admin_env):
    admin_env.cast.mode = "down"
    assert admin.get("/admin/profiles").status_code == 200


def test_names_are_escaped(admin, admin_env):
    admin_env.conn.execute("UPDATE profile SET name = ? WHERE id = 1", (XSS,))
    for url in ("/admin/profiles", "/admin/settings", "/admin", "/admin/history"):
        text = admin.get(url).text
        assert XSS not in text, url
    assert "&lt;script&gt;" in admin.get("/admin/profiles").text


def test_page_shows_every_avatar_as_a_radio_tile(admin):
    text = admin.get("/admin/profiles").text
    for key in AVATARS:
        assert f'value="{key}"' in text and f"/static/avatars/{key}.svg" in text


# --------------------------------------------------------------------------- add and edit


def test_add_appends_to_the_order(admin, admin_env):
    r = add(admin, "  Noor  ", "owl")
    assert r.status_code == 303
    last = rows(admin_env.conn)[-1]
    assert (last["name"], last["avatar"]) == ("Noor", "owl")
    assert last["sort_order"] > rows(admin_env.conn)[0]["sort_order"]


def test_add_without_avatar_is_allowed(admin, admin_env):
    assert add(admin, "Noor", "").status_code == 303
    assert rows(admin_env.conn)[-1]["avatar"] is None


@pytest.mark.parametrize("name, avatar", [("", "owl"), ("   ", "owl"), ("x" * 41, "owl"), ("Noor", "dragon"), ("Noor", "../x")])
def test_add_rejects_bad_input(admin, admin_env, name, avatar):
    r = add(admin, name, avatar)
    assert r.status_code == 422
    assert len(rows(admin_env.conn)) == 1


def test_edit_renames_and_sets_avatar(admin, admin_env):
    r = admin.post(f"/admin/profiles/{PROFILE}", data={"name": "Mila", "avatar": "fox"}, follow_redirects=False)
    assert r.status_code == 303
    row = rows(admin_env.conn)[0]
    assert (row["name"], row["avatar"]) == ("Mila", "fox")
    admin.post(f"/admin/profiles/{PROFILE}", data={"name": "Mila", "avatar": ""})
    assert rows(admin_env.conn)[0]["avatar"] is None


@pytest.mark.parametrize("data", [{"name": "", "avatar": "fox"}, {"name": "Mila", "avatar": "dragon"}])
def test_edit_rejects_bad_input(admin, admin_env, data):
    before = rows(admin_env.conn)
    assert admin.post(f"/admin/profiles/{PROFILE}", data=data).status_code == 422
    assert rows(admin_env.conn) == before


def test_edit_unknown_profile_is_404(admin):
    assert admin.post("/admin/profiles/999", data={"name": "X", "avatar": ""}).status_code == 404


# --------------------------------------------------------------------------- reorder


def test_move_swaps_neighbours(admin, admin_env):
    add(admin, "B", "owl")
    add(admin, "C", "cat")
    names = lambda: [r["name"] for r in rows(admin_env.conn)]  # noqa: E731
    assert names() == ["Household", "B", "C"]
    c = rows(admin_env.conn)[2]["id"]
    assert admin.post(f"/admin/profiles/{c}/move", data={"direction": "up"}, follow_redirects=False).status_code == 303
    assert names() == ["Household", "C", "B"]
    admin.post(f"/admin/profiles/{PROFILE}/move", data={"direction": "down"})
    assert names() == ["C", "Household", "B"]


def test_move_at_the_edge_changes_nothing(admin, admin_env):
    add(admin, "B", "owl")
    admin.post(f"/admin/profiles/{PROFILE}/move", data={"direction": "up"})
    assert [r["name"] for r in rows(admin_env.conn)] == ["Household", "B"]


def test_move_rejects_bad_direction_and_unknown_profile(admin):
    assert admin.post(f"/admin/profiles/{PROFILE}/move", data={"direction": "left"}).status_code == 422
    assert admin.post("/admin/profiles/999/move", data={"direction": "up"}).status_code == 404


def test_move_normalises_equal_sort_orders(admin, admin_env):
    conn = admin_env.conn
    conn.execute("INSERT INTO profile (id, name, sort_order, created_at) VALUES (2, 'B', 0, 'x')")
    conn.execute("UPDATE profile SET sort_order = 0")
    admin.post("/admin/profiles/2/move", data={"direction": "up"})
    assert [r["name"] for r in rows(conn)] == ["B", "Household"]


# --------------------------------------------------------------------------- photos


@pytestmark_ffmpeg
def test_upload_photo_replaces_the_old_one(admin, admin_env, jpeg_bytes):  # noqa: F811
    media = admin_env.config.media_dir
    r = admin.post(f"/admin/profiles/{PROFILE}/photo", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")},
                   follow_redirects=False)
    assert r.status_code == 303
    first = rows(admin_env.conn)[0]["picture_path"]
    assert first.startswith("profiles/") and (media / first).is_file()
    admin.post(f"/admin/profiles/{PROFILE}/photo", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")})
    second = rows(admin_env.conn)[0]["picture_path"]
    assert second != first and (media / second).is_file() and not (media / first).exists()
    assert admin.get(f"/img/profile/{PROFILE}.jpg").status_code == 200


@pytestmark_ffmpeg
def test_upload_photo_rejects_non_images(admin, admin_env):
    r = admin.post(f"/admin/profiles/{PROFILE}/photo", files={"file": ("a.txt", b"nope", "text/plain")})
    assert r.status_code == 422
    assert rows(admin_env.conn)[0]["picture_path"] is None


def test_upload_photo_unknown_profile_is_404(admin):
    assert admin.post("/admin/profiles/999/photo", files={"file": ("a.jpg", b"x", "image/jpeg")}).status_code == 404


@pytestmark_ffmpeg
def test_remove_photo(admin, admin_env, jpeg_bytes):  # noqa: F811
    admin.post(f"/admin/profiles/{PROFILE}/photo", files={"file": ("a.jpg", jpeg_bytes, "image/jpeg")})
    path = admin_env.config.media_dir / rows(admin_env.conn)[0]["picture_path"]
    assert admin.post(f"/admin/profiles/{PROFILE}/photo/remove", follow_redirects=False).status_code == 303
    assert rows(admin_env.conn)[0]["picture_path"] is None and not path.exists()


# --------------------------------------------------------------------------- delete


def test_delete_removes_the_profile_its_data_and_photo(admin, admin_env, pos):
    conn, media = admin_env.conn, admin_env.config.media_dir
    add(admin, "B", "owl")
    b = rows(conn)[1]["id"]
    (media / "profiles").mkdir(exist_ok=True)
    (media / "profiles" / "b.jpg").write_bytes(b"x")
    conn.execute("UPDATE profile SET picture_path = 'profiles/b.jpg' WHERE id = ?", (b,))
    pos(admin_env.ids.b1, 60, profile=b)
    r = admin.post(f"/admin/profiles/{b}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert [x["id"] for x in rows(conn)] == [PROFILE]
    assert conn.execute("SELECT COUNT(*) FROM playback_position WHERE profile_id = ?", (b,)).fetchone()[0] == 0
    assert not (media / "profiles" / "b.jpg").exists()


def test_delete_refuses_the_last_profile(admin, admin_env):
    r = admin.post(f"/admin/profiles/{PROFILE}/delete")
    assert r.status_code == 409
    assert len(rows(admin_env.conn)) == 1


def test_delete_refuses_a_profile_that_is_watching(admin, admin_env):
    add(admin, "B", "owl")
    b = rows(admin_env.conn)[1]["id"]
    watching(admin_env, b)
    assert admin.post(f"/admin/profiles/{b}/delete").status_code == 409
    assert len(rows(admin_env.conn)) == 2
    watching(admin_env, PROFILE)  # somebody else is watching: fine
    assert admin.post(f"/admin/profiles/{b}/delete", follow_redirects=False).status_code == 303


def test_delete_refused_when_the_cast_service_cannot_say(admin, admin_env):
    add(admin, "B", "owl")
    b = rows(admin_env.conn)[1]["id"]
    admin_env.cast.mode = "down"
    assert admin.post(f"/admin/profiles/{b}/delete").status_code == 409
    assert len(rows(admin_env.conn)) == 2


def test_delete_unknown_profile_is_404(admin):
    assert admin.post("/admin/profiles/999/delete").status_code == 404


def test_delete_button_asks_for_confirmation(admin):
    assert "confirm(" in admin.get("/admin/profiles").text


# --------------------------------------------------------------------------- the Origin check applies to every POST


@pytest.mark.parametrize("path, data", [
    ("/admin/profiles", {"name": "X", "avatar": ""}),
    (f"/admin/profiles/{PROFILE}", {"name": "X", "avatar": ""}),
    (f"/admin/profiles/{PROFILE}/move", {"direction": "down"}),
    (f"/admin/profiles/{PROFILE}/photo/remove", {}),
    (f"/admin/profiles/{PROFILE}/delete", {}),
])
def test_cross_origin_posts_are_refused(admin, admin_env, path, data):
    before = rows(admin_env.conn)
    assert admin.post(path, data=data, headers={"Origin": "http://evil.example"}).status_code == 403
    assert admin.post(path, data=data, headers={"Origin": ""}).status_code == 403
    assert rows(admin_env.conn) == before


def test_cross_origin_photo_upload_is_refused(admin):
    r = admin.post(f"/admin/profiles/{PROFILE}/photo", files={"file": ("a.jpg", b"x", "image/jpeg")},
                   headers={"Origin": "http://evil.example"})
    assert r.status_code == 403



def test_page_is_translated(admin):
    nl = admin.get("/admin/profiles", headers={"Accept-Language": "nl"}).text
    de = admin.get("/admin/profiles", headers={"Accept-Language": "de"}).text
    assert "Profiel toevoegen" in nl and "Profil hinzufügen" in de
