"""Installing a LoRA: the file a trainer returns, put where the engine looks."""
import json
import struct
from pathlib import Path

import pytest

from app import loras


def fake_lora(path: Path, halves: str = "decoder") -> Path:
    """A safetensors file with a header, which is all the app reads."""
    names = []
    if halves in ("planner", "both"):
        names.append("text_encoders.0.weight")
    if halves in ("decoder", "both"):
        names.append("diffusion_model.0.weight")
    header = {name: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for name in names}
    blob = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(blob)) + blob + b"\x00\x00")
    return path


def test_install_puts_the_file_and_a_note_beside_it(tmp_path):
    source = fake_lora(tmp_path / "returned.safetensors", halves="both")
    root = tmp_path / "loras"
    root.mkdir()

    done = loras.install(source, "Alicia", "alicia", "Alicia", root=root)

    assert done["name"] == "alicia.safetensors"
    assert done["kind"] == "both"
    assert (root / "alicia.safetensors").exists()
    note = (root / "alicia.txt").read_text(encoding="utf-8").split("\n")
    assert note[0] == "Alicia"
    assert "Trigger: alicia" in note
    assert any("corpus Alicia" in line for line in note)
    assert done["kind"] == "both", "what it holds is reported to the picker, which states it"


def test_install_groups_it_with_the_other_corpora(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    (root / "families.txt").write_text("chnsn = Chanson\n", encoding="utf-8")

    loras.install(fake_lora(tmp_path / "a.safetensors"), "Alicia", "alicia", "Alicia", root=root)

    text = (root / "families.txt").read_text(encoding="utf-8")
    assert f"alicia = {loras.CORPUS_FAMILY}" in text
    assert "chnsn = Chanson" in text, "what was there stays"


def test_two_corpora_that_share_a_first_word_are_not_mixed_up(tmp_path, monkeypatch):
    """The group is keyed on the whole file name. Keyed on the word in front of it,
    jane_doe_lora would claim jane_smith_lora and anything else starting jane."""
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)
    loras.install(fake_lora(tmp_path / "a.safetensors"), "Jane Doe", "janedoe", "Jane Doe", root=root)
    fake_lora(root / "jane_other.safetensors")

    entries = {entry["name"]: entry for entry in loras.catalogue(["jane_doe.safetensors", "jane_other.safetensors"])}
    assert entries["jane_doe.safetensors"]["family"] == loras.CORPUS_FAMILY
    assert entries["jane_doe.safetensors"]["title"] == "Jane Doe"
    assert "family" not in entries["jane_other.safetensors"]


def test_install_refuses_a_file_that_is_not_a_lora(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    junk = tmp_path / "not-a-lora.safetensors"
    junk.write_bytes(b"this is not a safetensors file")

    with pytest.raises(ValueError):
        loras.install(junk, "Nope", "", "Nope", root=root)
    assert list(root.iterdir()) == [], "nothing is written when the file is wrong"


def test_install_will_not_overwrite_one_already_there(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    source = fake_lora(tmp_path / "a.safetensors")

    loras.install(source, "Alicia", "alicia", "Alicia", root=root)
    with pytest.raises(ValueError, match="already"):
        loras.install(source, "Alicia", "alicia", "Alicia", root=root)


def test_install_says_so_when_there_is_no_model_folder():
    with pytest.raises(ValueError, match="model folder"):
        loras.install(Path("whatever.safetensors"), "Alicia", "", "Alicia", root=None)


# ------------------------------------------------------------- sharing a LoRA

STYLES = [{"title": "Jet", "prompt": "pop, synth, male vocal, key of A major", "tempo": 136},
          {"title": "My Love", "prompt": "soul, piano | drums, male vocal", "tempo": None}]


def test_learned_styles_travel_in_the_note_and_come_back_as_chips(tmp_path):
    lora = fake_lora(tmp_path / "jane_doe_lora.safetensors", "both")
    (tmp_path / "jane_doe_lora.txt").write_text(
        "Jane Doe\nTrigger: janedoe\n\nWorks up to 0.70.\nStyle: Old | stale | 99\n", encoding="utf-8")

    text = loras.note_with_styles(lora, STYLES)
    assert "Style: Old" not in text, "styles already in the note are replaced, not repeated"
    (tmp_path / "jane_doe_lora.txt").write_text(text, encoding="utf-8")
    note = loras.note_for(lora)

    assert note["title"] == "Jane Doe" and note["trigger"] == "janedoe"
    assert "Style:" not in note["note"], "the lines are chips, not prose under the picker"
    assert [s["title"] for s in note["styles"]] == ["Jet", "My Love"]
    assert note["styles"][0]["prompt"] == "pop, synth, male vocal, key of A major" and note["styles"][0]["tempo"] == 136
    assert note["styles"][1]["tempo"] is None and "|" not in note["styles"][1]["prompt"]


def test_a_bundle_installs_on_another_machine_with_its_note(tmp_path):
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    mine.mkdir(), theirs.mkdir()
    lora = fake_lora(mine / "jane_doe_lora.safetensors", "both")
    (mine / "jane_doe_lora.txt").write_text("Jane Doe\nTrigger: janedoe\n", encoding="utf-8")
    zipped = loras.bundle(lora, STYLES, tmp_path / "shared.zip")

    done = loras.install_shared(zipped, "shared.zip", root=theirs)

    assert done == {"name": "jane_doe_lora.safetensors", "kind": "both", "styles": 2}
    assert (theirs / "jane_doe_lora.safetensors").read_bytes() == lora.read_bytes()
    assert loras.note_for(theirs / "jane_doe_lora.safetensors")["trigger"] == "janedoe"
    assert loras.families(theirs)["jane_doe_lora"] == loras.INSTALLED_FAMILY
    assert zipped.exists(), "the upload is the caller's to remove"


def test_a_bare_safetensors_file_installs_too(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    done = loras.install_shared(fake_lora(tmp_path / "upload.tmp"), "someones_lora.safetensors", root=root)
    assert done["name"] == "someones_lora.safetensors" and done["styles"] == 0
    assert (root / "someones_lora.txt").read_text(encoding="utf-8").strip() == "someones_lora"


def test_a_shared_lora_does_not_replace_one_already_there(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    fake_lora(root / "taken.safetensors")
    with pytest.raises(ValueError):
        loras.install_shared(fake_lora(tmp_path / "upload.tmp"), "taken.safetensors", root=root)


def test_a_zip_without_a_lora_is_refused(tmp_path):
    import zipfile
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as archive:
        archive.writestr("notes.txt", "hello")
    with pytest.raises(ValueError):
        loras.install_shared(junk, "junk.zip", root=tmp_path)


def test_download_and_install_through_the_app(client, tmp_path, monkeypatch):
    import io
    import zipfile
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)
    fake_lora(root / "shared_lora.safetensors", "both")
    (root / "shared_lora.txt").write_text("Shared\nTrigger: sharedword\n", encoding="utf-8")

    got = client.get("/api/loras/shared_lora.safetensors/download")
    assert got.status_code == 200
    assert sorted(zipfile.ZipFile(io.BytesIO(got.content)).namelist()) == ["shared_lora.safetensors", "shared_lora.txt"]
    assert client.get("/api/loras/..%2Fsecret.safetensors/download").status_code == 404

    (root / "shared_lora.safetensors").rename(root / "moved.bin")
    (root / "shared_lora.txt").unlink()
    put = client.post("/api/loras/install", files={"file": ("shared_lora.zip", got.content, "application/zip")})
    assert put.status_code == 200 and put.json()["name"] == "shared_lora.safetensors"
    assert loras.note_for(root / "shared_lora.safetensors")["trigger"] == "sharedword"


def test_deleting_a_lora_takes_its_note_log_and_group_line_with_it(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    fake_lora(root / "jane_test.safetensors")
    (root / "jane_test.txt").write_text("Jane Doe\n", encoding="utf-8")
    (root / "jane_test_log.json").write_text("[]", encoding="utf-8")
    fake_lora(root / "mltnt_roots.safetensors")
    (root / "families.txt").write_text("# groups\nmltnt = MLTNT\n\njane_test = Installed\n\nother_lora = Your corpora\n",
                                       encoding="utf-8")

    gone = loras.remove("jane_test.safetensors", root=root)

    assert sorted(p.name for p in root.iterdir()) == ["families.txt", "mltnt_roots.safetensors"]
    assert "its line in families.txt" in gone
    families = loras.families(root)
    assert "jane_test" not in families
    assert families["mltnt"] == "MLTNT", "a set's prefix line stays: other files share it"
    assert families["other_lora"] == "Your corpora"


def test_the_app_deletes_a_lora_and_forgets_it_on_the_corpus(client, tmp_path, monkeypatch):
    import time
    from app.db import execute, one
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)
    fake_lora(root / "alicia_lora.safetensors")
    execute("""INSERT INTO identities(id, name, trigger_word, description, voice, folder, consent, created_at, lora)
               VALUES('c1', 'Alicia', 'alicia', '', 'female', '/m', 1, ?, 'alicia_lora.safetensors')""", (time.time(),))

    assert client.delete("/api/loras/alicia_lora.safetensors").status_code == 200
    assert not (root / "alicia_lora.safetensors").exists()
    assert one("SELECT lora FROM identities WHERE id = 'c1'")["lora"] is None
    assert client.delete("/api/loras/alicia_lora.safetensors").status_code == 404
    assert client.delete("/api/loras/..%2Fsecret.safetensors").status_code == 404


# ------------------------------------------------------ a LoRA's own strengths

def test_strengths_are_written_under_the_trigger_and_read_back(tmp_path):
    lora = fake_lora(tmp_path / "june_lora.safetensors", "both")
    (tmp_path / "june_lora.txt").write_text("june\nTrigger: june\n\nTrained from the corpus june.\n", encoding="utf-8")

    loras.set_strengths(lora, 0.8, 0.6)
    lines = (tmp_path / "june_lora.txt").read_text(encoding="utf-8").split("\n")
    assert lines[:3] == ["june", "Trigger: june", "Strengths: Planner 0.80, Sound 0.60"]
    note = loras.note_for(lora)
    assert note["strengths"] == {"planner": 0.8, "sound": 0.6}
    assert "Strengths" not in note["note"], "a setting, not prose under the picker"

    loras.set_strengths(lora, 0.7, 0.5)
    assert (tmp_path / "june_lora.txt").read_text(encoding="utf-8").count("Strengths:") == 1, "replaced, not added"
    loras.set_strengths(lora, None, None)
    assert "strengths" not in loras.note_for(lora), "both empty clears them"


def test_a_lora_without_a_note_gets_one_for_its_strengths(tmp_path):
    lora = fake_lora(tmp_path / "bare.safetensors")
    loras.set_strengths(lora, 1.0, 0.5)
    assert (tmp_path / "bare.txt").read_text(encoding="utf-8").split("\n")[:2] == ["bare", "Strengths: Planner 1.00, Sound 0.50"]


def test_strengths_travel_in_a_download(tmp_path):
    import zipfile
    lora = fake_lora(tmp_path / "june_lora.safetensors", "both")
    (tmp_path / "june_lora.txt").write_text("june\nTrigger: june\n", encoding="utf-8")
    loras.set_strengths(lora, 0.8, 0.6)
    note = zipfile.ZipFile(loras.bundle(lora, [], tmp_path / "out.zip")).read("june_lora.txt").decode()
    assert "Strengths: Planner 0.80, Sound 0.60" in note


def test_the_app_saves_a_loras_strengths(client, tmp_path, monkeypatch):
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)
    fake_lora(root / "june_lora.safetensors", "both")
    saved = client.put("/api/loras/june_lora.safetensors/strengths", json={"planner": 0.8, "sound": 0.6})
    assert saved.status_code == 200 and saved.json()["strengths"] == {"planner": 0.8, "sound": 0.6}
    assert client.put("/api/loras/june_lora.safetensors/strengths", json={"planner": 0.8}).status_code == 400
    assert client.put("/api/loras/june_lora.safetensors/strengths", json={"planner": 9, "sound": 0.6}).status_code == 422
    assert client.put("/api/loras/nope.safetensors/strengths", json={"planner": 0.8, "sound": 0.6}).status_code == 404
