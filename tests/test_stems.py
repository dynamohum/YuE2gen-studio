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
    assert steps[4][1] == "Separating, model 2 of 4, 5%"
    assert steps[-1] == (0.96, "Writing the stems")


def test_a_single_model():
    steps = run(1, [0, 50, 100])
    assert steps[1] == (0.5, "Separating 50%")
    assert steps[-1] == (0.95, "Separating 100%")
