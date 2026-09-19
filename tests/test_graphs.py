from app.jobs import (PLAN_VARIETY, build_plan_graph, build_render_graph, build_transcribe_graph,
                      extract_audio_item, extract_text_output)


TAKE = {"id": "t1", "checkpoint": "ck", "style": "rock", "lyrics": "la", "abc": "X:1", "seed": 42,
        "mode": "melody", "max_duration": 120, "variety": "wild"}


def test_templates_are_fresh_copies():
    first = build_transcribe_graph("a.wav")
    second = build_transcribe_graph("b.wav")
    assert first["1"]["inputs"]["audio"] == "a.wav" and second["1"]["inputs"]["audio"] == "b.wav"


def test_plan_graph_uses_the_variety():
    node = build_plan_graph(TAKE)["2"]["inputs"]
    assert node["temperature"] == PLAN_VARIETY["wild"]["temperature"]
    assert node["mode"] == "full" and node["seed"] == 42


def test_render_graph():
    graph = build_render_graph(TAKE)
    assert graph["11"]["inputs"]["abc"] == "X:1"
    assert graph["11"]["inputs"]["max_duration"] == 120.0
    assert graph["14"]["inputs"]["seed"] == 42
    # A new prefix every run, so the engine never answers from its output cache.
    assert graph["16"]["inputs"]["filename_prefix"].startswith("yue2studio/t1-")


def test_extractors():
    job = {
        "prompt": [0, "pid", {"3": {"class_type": "PreviewAny"}, "16": {"class_type": "SaveAudioAdvanced"}}],
        "outputs": {"3": {"text": ["X:1\nabc"]}, "16": {"audio": [{"filename": "take.flac", "subfolder": "yue2studio"}]}},
    }
    assert extract_text_output(job, "PreviewAny") == "X:1\nabc"
    assert extract_audio_item(job, "SaveAudioAdvanced")["filename"] == "take.flac"
    assert extract_text_output({}, "PreviewAny") is None
