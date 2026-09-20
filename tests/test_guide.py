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
                   "Instrumentals", "Voices and Identities", "Style LoRAs", "Stems",
                   "The library", "Settings", "When something is wrong"):
        assert any(wanted in head for head in headings), f"the guide says nothing about {wanted}"


def test_the_guide_does_not_promise_what_is_not_built():
    text = GUIDE.read_text(encoding="utf-8").lower()
    for unbuilt in ("mixing desk", "timeline editor", "train a lora"):
        assert unbuilt not in text, f"the guide describes {unbuilt}, which is not in the app"
