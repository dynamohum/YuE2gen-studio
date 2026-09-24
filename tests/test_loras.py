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
    paul_mccartney_lora would claim paul_shields_lora and anything else starting paul."""
    root = tmp_path / "loras"
    root.mkdir()
    monkeypatch.setattr(loras, "folder", lambda: root)
    loras.install(fake_lora(tmp_path / "a.safetensors"), "Paul McCartney", "paulmccartney", "Paul McCartney", root=root)
    fake_lora(root / "paul_other.safetensors")

    entries = {entry["name"]: entry for entry in loras.catalogue(["paul_mccartney.safetensors", "paul_other.safetensors"])}
    assert entries["paul_mccartney.safetensors"]["family"] == loras.CORPUS_FAMILY
    assert entries["paul_mccartney.safetensors"]["title"] == "Paul McCartney"
    assert "family" not in entries["paul_other.safetensors"]


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
    lora = fake_lora(tmp_path / "paul_mccartney_lora.safetensors", "both")
    (tmp_path / "paul_mccartney_lora.txt").write_text(
        "Paul McCartney\nTrigger: paulmccartney\n\nWorks up to 0.70.\nStyle: Old | stale | 99\n", encoding="utf-8")

    text = loras.note_with_styles(lora, STYLES)
    assert "Style: Old" not in text, "styles already in the note are replaced, not repeated"
    (tmp_path / "paul_mccartney_lora.txt").write_text(text, encoding="utf-8")
    note = loras.note_for(lora)

    assert note["title"] == "Paul McCartney" and note["trigger"] == "paulmccartney"
    assert "Style:" not in note["note"], "the lines are chips, not prose under the picker"
    assert [s["title"] for s in note["styles"]] == ["Jet", "My Love"]
    assert note["styles"][0]["prompt"] == "pop, synth, male vocal, key of A major" and note["styles"][0]["tempo"] == 136
    assert note["styles"][1]["tempo"] is None and "|" not in note["styles"][1]["prompt"]


def test_a_bundle_installs_on_another_machine_with_its_note(tmp_path):
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    mine.mkdir(), theirs.mkdir()
    lora = fake_lora(mine / "paul_mccartney_lora.safetensors", "both")
    (mine / "paul_mccartney_lora.txt").write_text("Paul McCartney\nTrigger: paulmccartney\n", encoding="utf-8")
    zipped = loras.bundle(lora, STYLES, tmp_path / "shared.zip")

    done = loras.install_shared(zipped, "shared.zip", root=theirs)

    assert done == {"name": "paul_mccartney_lora.safetensors", "kind": "both", "styles": 2}
    assert (theirs / "paul_mccartney_lora.safetensors").read_bytes() == lora.read_bytes()
    assert loras.note_for(theirs / "paul_mccartney_lora.safetensors")["trigger"] == "paulmccartney"
    assert loras.families(theirs)["paul_mccartney_lora"] == loras.INSTALLED_FAMILY
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
