from app.stems import Progress


def run(passes, sequence):
    parser = Progress(passes)
    return [step for step in (parser.feed(p) for p in sequence) if step]


def test_a_bag_of_four_models_rises_steadily_through_writing():
    # What htdemucs_ft printed for a 20 second take, writing two MP3 stems.
    printed = [6, 21, 66, 90, 5, 39, 84, 0, 33, 92, 9, 49, 99, 25, 50, 75, 100, 25, 50, 75, 100]
    steps = run(4, printed)
    figures = [frac for frac, _ in steps]
    assert figures == sorted(figures), figures
    assert steps[4][1] == "Separating (model 2 of 4)"
    assert steps[-1] == (0.96, "Writing the stems")


def test_a_single_model():
    steps = run(1, [0, 50, 100])
    assert steps[1] == (0.5, "Separating")
    assert steps[-1] == (0.95, "Separating")


def test_asking_for_stems_is_answered_for_a_take_and_a_recording(client, tmp_path):
    """The request queues the job and says so.  A log line after the queueing once
    named a field the request does not have, and every request came back as an error
    although the stems were made."""
    from app.db import execute
    from app.jobs import STEM_QUEUE
    from conftest import make_take, tone

    audio = tone(tmp_path / "take.flac", 1.0)
    take = make_take(audio_path=str(audio))
    execute("""INSERT INTO sources(id, title, filename, stored_path, sha256, created_at)
               VALUES('src1', 'Song', 'song.flac', ?, 'abc', 1.0)""", (str(audio),))
    try:
        for url in (f"/api/takes/{take['id']}/stems", "/api/sources/src1/stems"):
            answer = client.post(url, json={"model": "htdemucs", "stems": ["vocals"]})
            assert answer.status_code == 200, answer.text
            assert answer.json()["id"]
    finally:
        while not STEM_QUEUE.empty():
            STEM_QUEUE.get_nowait()
