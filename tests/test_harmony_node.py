"""The engine's yue2_harmony node: chord tracking and scoring, without ComfyUI."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

NODE = Path(__file__).resolve().parents[1] / "engine" / "custom_nodes" / "yue2_harmony" / "__init__.py"


@pytest.fixture(scope="module")
def harmony():
    stub = types.ModuleType("comfy.text_encoders.yue2")
    stub.EOD = 1000
    stub.distribution = lambda *a, **k: None
    saved = {k: sys.modules.get(k) for k in ("comfy", "comfy.text_encoders", "comfy.text_encoders.yue2")}
    sys.modules.update({"comfy": types.ModuleType("comfy"), "comfy.text_encoders": types.ModuleType("comfy.text_encoders"),
                        "comfy.text_encoders.yue2": stub})
    spec = importlib.util.spec_from_file_location("yue2_harmony_under_test", NODE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for key, value in saved.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value


VOCAB = ['K:D\n', 'V: Vocal name="Vocal"\n', '"D"', 'z16|', '"Gmaj7"', '"A"', '"Bm"', '"G"', '"Gsus2"',
         '"Bb"', '"C"', '"F', '#m"', '"D', '"', '\n', '"Dsus2"']
IDS = {text: i for i, text in enumerate(VOCAB)}


def feed(harmony, mode, symbols, **kw):
    """A tracker that has read the key line, a header with a quoted name, then symbols."""
    t = harmony.HarmonyTracker(VOCAB, mode, kw.pop("strength", 8.0), **kw)
    history = [IDS['K:D\n'], IDS['V: Vocal name="Vocal"\n']]
    for symbol in symbols:
        history += [IDS[symbol], IDS['z16|']]
    t.feed(history)
    return t


def value(harmony, t, text):
    """What choosing text next would cost (negative: a bonus)."""
    _, partial, done = harmony.walk(text, t.line, t.partial)
    if t.mode == "spelling":
        symbol = done[0] if done else partial
        return t.spelling_penalty(done, partial) + t.hold_penalty(harmony.root_of(symbol))
    return t.root_penalty(harmony.root_of(done[0] if done else partial))


LOOP = ['"D"', '"Gmaj7"', '"A"', '"D"']


def test_header_quotes_are_not_chords(harmony):
    assert list(feed(harmony, "spelling", LOOP).changes) == ["D", "Gmaj7", "A", "D"]


def test_spelling_mode_lets_a_chord_be_respelled(harmony):
    t = feed(harmony, "spelling", LOOP)
    assert value(harmony, t, '"Gmaj7"') == 8.0 * 1 / 4
    assert value(harmony, t, '"Gsus2"') == 0        # a new spelling counts as a new chord
    assert value(harmony, t, '"D"') == 0            # holding the current chord is free


def test_root_mode_treats_spellings_as_one_chord(harmony):
    t = feed(harmony, "root", LOOP)
    assert value(harmony, t, '"Gsus2"') == value(harmony, t, '"Gmaj7"') == 8.0 * 1 / 4
    assert value(harmony, t, '"Bm"') == 0


def test_root_mode_limits_holding(harmony):
    t = feed(harmony, "root", ['"A"', '"D"', '"D"', '"D"'], hold_limit=2)
    assert t.held == 3
    assert value(harmony, t, '"D"') == 8.0 * (1 + 3 - 2) / 4


def test_spelling_mode_limits_holding_by_root(harmony):
    t = feed(harmony, "spelling", ['"A"', '"D"', '"D"', '"D"'], hold_limit=2)
    assert t.held == 3
    assert value(harmony, t, '"D"') == 8.0 * (1 + 3 - 2) / 4
    # A respelling of the same root does not escape the limit: it keeps the count.
    respelled = feed(harmony, "spelling", ['"A"', '"D"', '"D"', '"Dsus2"'], hold_limit=2)
    assert respelled.held == 3


def test_outside_bonus_only_on_a_change_and_below_the_limit(harmony):
    t = feed(harmony, "root", LOOP, outside_bonus=3.0, outside_limit=0.25)
    assert t.scale == {1, 2, 4, 6, 7, 9, 11}        # D major
    assert value(harmony, t, '"Bb"') == -3.0        # a change to a root outside the key
    held = feed(harmony, "root", ['"D"', '"C"'], outside_bonus=3.0)
    assert value(harmony, held, '"C"') == 0         # holding an outside chord earns nothing
    busy = feed(harmony, "root", ['"D"', '"C"', '"D"'], outside_bonus=3.0, outside_limit=0.25)
    assert value(harmony, busy, '"Bb"') == 0        # a third of recent chords are already outside


def test_an_accidental_after_the_letter_decides_the_root(harmony):
    t = harmony.HarmonyTracker(VOCAB, "root", 8.0, outside_bonus=3.0)
    t.feed([IDS['K:D\n'], IDS['"D"'], IDS['z16|'], IDS['"F']])   # the planner has written "F
    assert t.partial == "F"
    assert value(harmony, t, '#m"') == 0      # F#m: F# is in D major, so no bonus
    assert value(harmony, t, '"') == -3.0     # F natural is outside it


def test_off_is_inactive(harmony):
    assert not harmony.HarmonyTracker(VOCAB, "root", 0.0).active
    assert not harmony.HarmonyTracker(VOCAB, "spelling", 0.0, outside_bonus=5.0).active   # the bonus is root mode only
