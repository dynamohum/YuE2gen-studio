from app.db import one

from conftest import make_take


def test_every_take_starts_in_default(client):
    take = make_take()
    assert one("SELECT space_id FROM takes WHERE id = ?", (take["id"],))["space_id"] == "default"
    spaces = client.get("/api/spaces").json()
    assert [(s["id"], s["name"], s["takes"]) for s in spaces] == [("default", "Default", 1)]


def test_create_rename_and_list_in_order(client):
    zed = client.post("/api/spaces", json={"name": "  Zed   demos "}).json()
    assert zed["name"] == "Zed demos"
    client.post("/api/spaces", json={"name": "alpha"})
    assert [s["name"] for s in client.get("/api/spaces").json()] == ["Default", "alpha", "Zed demos"]
    assert client.post("/api/spaces", json={"name": "ALPHA"}).status_code == 409
    assert client.post("/api/spaces", json={"name": "   "}).status_code == 400
    assert client.put(f"/api/spaces/{zed['id']}", json={"name": "zed DEMOS"}).json()["name"] == "zed DEMOS"
    assert client.put("/api/spaces/nope", json={"name": "x"}).status_code == 404


def test_move_and_filter(client):
    space = client.post("/api/spaces", json={"name": "Covers"}).json()
    first, second = make_take(), make_take()
    assert client.post(f"/api/takes/{first['id']}/move", json={"space_id": space["id"]}).status_code == 200
    assert [t["id"] for t in client.get(f"/api/takes?space_id={space['id']}").json()] == [first["id"]]
    assert [t["id"] for t in client.get("/api/takes?space_id=default").json()] == [second["id"]]
    assert len(client.get("/api/takes").json()) == 2
    assert client.post(f"/api/takes/{first['id']}/move", json={"space_id": "nope"}).status_code == 404
    assert client.post("/api/takes/nope/move", json={"space_id": "default"}).status_code == 404


def test_deleting_a_space_keeps_its_takes(client):
    space = client.post("/api/spaces", json={"name": "Scratch"}).json()
    take = make_take()
    client.post(f"/api/takes/{take['id']}/move", json={"space_id": space["id"]})
    assert client.delete(f"/api/spaces/{space['id']}").json() == {"deleted": True, "moved": 1}
    assert one("SELECT space_id FROM takes WHERE id = ?", (take["id"],))["space_id"] == "default"
    assert client.delete("/api/spaces/default").status_code == 400


def test_new_songs_land_in_the_chosen_space(client):
    space = client.post("/api/spaces", json={"name": "Ideas"}).json()
    body = {"lyrics": "[Verse]\nla la"}
    song = client.post("/api/songs", json={**body, "space_id": space["id"]}).json()
    assert one("SELECT space_id FROM takes WHERE id = ?", (song["id"],))["space_id"] == space["id"]
    assert client.post("/api/songs", json={**body, "space_id": "gone"}).status_code == 404
