"""The trainer's progress reaches the app log: its stages, the songs it kept, the loss and KL."""
import logging

from app.engine import Engine


def running(engine: Engine, stage: str) -> dict:
    engine.progress["p1"] = {"stage": stage, "frac": 0.0, "value": None, "max": None, "executing": True}
    return engine.progress["p1"]


def send(engine: Engine, **data) -> None:
    # The trainer's messages carry no prompt id: they belong to whichever training is running.
    engine._handle_ws({"type": "fsaudio.train", "data": {"node": "5", **data}})


def test_songs_left_out_of_the_planner_are_warned_about(caplog):
    engine = Engine("http://engine:8188")
    rec = running(engine, "FSAudioDatasetBuilder")
    with caplog.at_level(logging.INFO, logger="yue2.engine"):
        send(engine, stage="Tokenizing", pct=0, detail="harbour-lights")
        send(engine, stage="Done", pct=100, detail="17 songs, 73.0 min")
        rec["stage"] = "FSAudioArtistTrainer"
        send(engine, stage="Training artist", detail="16 artist / 10373 regularizer songs | planner r64")
    text = caplog.text
    assert "harbour-lights" not in text          # per-song stages stay out of the log
    assert "Training: Done: 17 songs, 73.0 min" in text
    assert "Training: Training artist: 16 artist" in text
    assert "1 of 17 songs were too long for the Planner's context" in text


def test_no_warning_when_every_song_is_kept(caplog):
    engine = Engine("http://engine:8188")
    rec = running(engine, "FSAudioDatasetBuilder")
    with caplog.at_level(logging.INFO, logger="yue2.engine"):
        send(engine, stage="Done", pct=100, detail="12 songs, 38.0 min")
        rec["stage"] = "FSAudioArtistTrainer"
        send(engine, stage="Training artist", detail="12 artist / 10373 regularizer songs")
    assert "too long" not in caplog.text


def test_evaluations_and_every_25th_step_are_logged_with_the_kl(caplog):
    engine = Engine("http://engine:8188")
    rec = running(engine, "FSAudioArtistTrainer")
    with caplog.at_level(logging.INFO, logger="yue2.engine"):
        send(engine, step=0, total=50, evals={"artist": 5.6758, "regularizer": 3.6087, "decoder": 1.3142})
        for step in (1, 24, 25):
            send(engine, step=step, total=50, loss=4.5, kl=0.00105, decoder_loss=1.285)
    text = caplog.text
    assert "Training step 0 evaluation: artist 5.676, regularizer 3.609, decoder 1.314" in text
    assert "Training step 25/50: loss 4.500, KL 0.0010, decoder loss 1.285" in text
    assert "Training step 24/" not in text and "Training step 1/" not in text
    assert rec["value"] == 25 and rec["frac"] == 0.5
