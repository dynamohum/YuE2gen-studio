"""A style LoRA from elsewhere: reading what is in the file, and chaining it.

The app's own two LoRAs are each one half of the model and are applied with the
other strength at zero. A style LoRA is usually both halves and wants both, so
these tests pin the thing that would otherwise go unnoticed: that the planner
half is switched on, in the run where the plan is written as well as the render.
"""
import json
import struct

import pytest

from app import jobs, loras
from app.jobs import build_plan_graph, build_render_graph, with_plan_lora, with_style_lora

from conftest import make_take


def safetensors(path, names):
    """A file with a real header and no tensor data behind it. The header is all
    the app reads, so this is enough to be parsed exactly as a LoRA is."""
    header = {name: {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]} for name in names}
    raw = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * 4)
    return path


def test_a_file_holding_both_halves_is_read_as_both(tmp_path):
    path = safetensors(tmp_path / "reggae.safetensors",
                       ["text_encoders.layer.0.weight", "diffusion_model.block.1.weight"])
    assert loras.kind_of(loras.names_in(path)) == "both"


def test_the_apps_own_loras_are_each_one_half(tmp_path):
    planner = safetensors(tmp_path / "inst.safetensors", ["text_encoders.a.weight"])
    decoder = safetensors(tmp_path / "real.safetensors", ["diffusion_model.a.weight"])
    assert loras.kind_of(loras.names_in(planner)) == "planner"
    assert loras.kind_of(loras.names_in(decoder)) == "decoder"


def test_a_lora_in_another_layout_is_not_offered(tmp_path):
    """Some YuE2 LoRAs ship PEFT-style keys, which this engine cannot chain."""
    path = safetensors(tmp_path / "other.safetensors", ["model.layers.0.mlp.lora_down.weight"])
    kind = loras.kind_of(loras.names_in(path))
    assert kind == "other"
    assert not loras.usable({"name": "other.safetensors", "kind": kind, "reserved": False})


def test_a_file_that_is_not_safetensors_is_reported_not_guessed(tmp_path):
    path = tmp_path / "broken.safetensors"
    path.write_bytes(b"not a safetensors file at all")
    entry = loras.describe("broken.safetensors", tmp_path)
    assert entry["kind"] == "unknown"


def test_the_catalogue_marks_the_two_the_app_applies_itself():
    entries = {e["name"]: e for e in loras.catalogue([loras.RESERVED and next(iter(loras.RESERVED))])}
    assert all(entry["reserved"] for entry in entries.values())


def test_the_catalogue_keeps_what_the_engine_reported_without_the_files():
    """App and engine on different machines: the names are still the truth."""
    entries = loras.catalogue(["somebody-elses.safetensors"])
    assert entries[0]["name"] == "somebody-elses.safetensors"
    assert entries[0]["kind"] in ("unknown", "other", "both", "planner", "decoder")


def test_a_style_lora_uses_both_strengths_in_the_render():
    graph = {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "11": {"class_type": "YuE2GenerateMusic", "inputs": {"clip": ["10", 1]}},
        "14": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
    }
    with_style_lora(graph, "reggae.safetensors", strength_model=1.0, strength_clip=0.5)
    node = graph["27"]
    assert node["inputs"]["lora_name"] == "reggae.safetensors"
    assert node["inputs"]["strength_model"] == 1.0
    assert node["inputs"]["strength_clip"] == 0.5
    assert graph["14"]["inputs"]["model"] == ["27", 0]


def test_the_planner_half_reaches_the_run_that_writes_the_plan():
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "2": {"class_type": "YuE2GenerateABC", "inputs": {"clip": ["1", 1]}},
    }
    with_plan_lora(graph, "1", "reggae.safetensors", ("2",), strength_clip=0.5)
    assert graph["21"]["inputs"]["strength_clip"] == 0.5
    assert graph["21"]["inputs"]["strength_model"] == 0.0
    assert graph["2"]["inputs"]["clip"] == ["21", 1]


def test_an_instrumental_keeps_its_own_lora_and_gains_the_style_one():
    """Both chain onto the planner, and the order must not drop either."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "2": {"class_type": "YuE2GenerateABC", "inputs": {"clip": ["1", 1]}},
    }
    from app import instrumental
    instrumental.with_lora(graph, "1", "inst.safetensors", ("2",), 1.0)
    with_plan_lora(graph, "1", "reggae.safetensors", ("2",), strength_clip=0.5)
    assert graph["20"]["inputs"]["lora_name"] == "inst.safetensors"
    assert graph["21"]["inputs"]["clip"] == ["20", 1]
    assert graph["2"]["inputs"]["clip"] == ["21", 1]


def test_a_take_without_a_style_lora_has_no_extra_node():
    take = make_take(kind="song", abc="X:1\n", status="planned")
    graph = build_render_graph(dict(take))
    assert "27" not in graph


def test_a_takes_choice_reaches_both_graphs():
    take = dict(make_take(kind="song", abc="X:1\n", status="planned"))
    take.update(style_lora="reggae.safetensors", style_lora_model=0.8, style_lora_clip=0.4)
    render = build_render_graph(take)
    assert render["27"]["inputs"]["strength_model"] == 0.8
    assert render["27"]["inputs"]["strength_clip"] == 0.4
    plan = build_plan_graph(take)
    assert plan["21"]["inputs"]["strength_clip"] == 0.4


def test_one_file_chosen_as_both_a_voice_and_a_style_is_chained_once():
    """An Identity's LoRA and a style LoRA can be the same file. Applying it
    twice would double it, quietly, and only for people who own Identities."""
    take = dict(make_take(kind="song", abc="X:1\n", status="planned"))
    take.update(voice_lora="paulshields_best.safetensors", voice_lora_strength=1.0,
                style_lora="paulshields_best.safetensors", style_lora_model=0.6,
                style_lora_clip=0.9)
    graph = build_render_graph(take)
    assert "26" not in graph, "the identity chain should give way to the style one"
    assert graph["27"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["27"]["inputs"]["strength_model"] == 0.6
    assert graph["27"]["inputs"]["strength_clip"] == 0.9


def test_a_different_voice_and_style_lora_both_apply():
    take = dict(make_take(kind="song", abc="X:1\n", status="planned"))
    take.update(voice_lora="paulshields_best.safetensors", voice_lora_strength=1.0,
                style_lora="mltnt_roots.safetensors", style_lora_model=1.0, style_lora_clip=0.5)
    graph = build_render_graph(take)
    assert graph["26"]["inputs"]["lora_name"] == "paulshields_best.safetensors"
    assert graph["27"]["inputs"]["lora_name"] == "mltnt_roots.safetensors"
    # Chained, not competing: the sampler takes the last one in the chain.
    assert graph["14"]["inputs"]["model"] == ["27", 0]
