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
    assert "score and sound" in "\n".join(note), "the note says which halves it holds"


def test_install_groups_it_under_the_corpus(tmp_path):
    root = tmp_path / "loras"
    root.mkdir()
    (root / "families.txt").write_text("chnsn = Chanson\n", encoding="utf-8")

    loras.install(fake_lora(tmp_path / "a.safetensors"), "Alicia", "alicia", "Alicia", root=root)

    text = (root / "families.txt").read_text(encoding="utf-8")
    assert "alicia = Alicia" in text
    assert "chnsn = Chanson" in text, "what was there stays"
    assert loras.families(root)["alicia"] == "Alicia"


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
