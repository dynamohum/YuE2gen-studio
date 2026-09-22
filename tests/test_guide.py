"""The guide is a page in the app, so it has to be there when the app is."""
import re
from pathlib import Path

GUIDE = Path(__file__).resolve().parent.parent / "app" / "static" / "guide.md"


def test_the_guide_is_served(client):
    r = client.get("/guide")
    assert r.status_code == 200
    assert "guide.md" in r.text, "the page has to fetch the markdown it renders"
    assert "{{VERSION}}" not in r.text, "the version has to be stamped, or caching lies"


def test_the_markdown_ships_with_the_app(client):
    """It lives under app/, not docs/, because only app/ is copied into the image."""
    r = client.get("/static/guide.md")
    assert r.status_code == 200
    assert r.text.startswith("# YuE2 Studio")


def test_the_renderer_is_vendored(client):
    assert client.get("/static/marked.min.js").status_code == 200


def test_every_feature_has_a_section():
    """A guide that quietly stops covering things is worse than no guide, so the
    headings are pinned to the features they describe."""
    text = GUIDE.read_text(encoding="utf-8")
    headings = set(re.findall(r"^#{2,3} (.+)$", text, re.M))
    for wanted in ("Your first song", "Harmony", "Rendering", "Covering a recording",
                   "Instrumentals", "Voices", "Corpora", "Style LoRAs", "Stems",
                   "The library", "Settings", "When something is wrong"):
        assert any(wanted in head for head in headings), f"the guide says nothing about {wanted}"


def test_the_guide_does_not_promise_what_is_not_built():
    text = GUIDE.read_text(encoding="utf-8").lower()
    for unbuilt in ("mixing desk", "timeline editor"):
        assert unbuilt not in text, f"the guide describes {unbuilt}, which is not in the app"


def test_the_guide_says_training_is_not_shipped():
    """It is off, and the guide has to say so rather than describe a button that is
    not there.  A guide that offered it as finished would waste an hour of somebody's
    GPU on a file that does not sound like their corpus."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "not shipped" in text, "the guide says training is off, not merely shaky"
    assert "WITH_TRAINER=1" in text, "and how to turn it on anyway"
    assert "TRAINING_ENABLED=1" in text, "both halves, or it stays hidden"


def test_the_guide_points_at_what_does_work():
    """Turning the button off is only half the message: exporting a set and installing
    a LoRA trained elsewhere is the route that produces something usable, and it is
    unaffected."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "Install a LoRA" in text
    assert "Export the training set" in text
