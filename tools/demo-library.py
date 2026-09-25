#!/usr/bin/env python3
"""Build a demo library for the README screenshots.

The screenshots in docs/screenshots must not show a real library: the takes
there are someone's work in progress, and an Identity holds their own songs.
So this writes a separate data folder with invented takes, an invented
Identity and one recording to cover, and hard links real rendered audio into
it so the waveforms, durations and the player are genuine.

    python3 tools/demo-library.py --from data --to ~/scratch/yue2-docs/data

Then run the app against that folder and take the shots.  Nothing here touches
the library it reads from: it only ever reads, and hard links cost no disk.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

NOW = time.time()
HOUR = 3600.0


def slug(text: str, limit: int = 40) -> str:
    import re
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return re.sub(r"-{2,}", "-", text).strip("-")[:limit].strip("-") or "untitled"


# Which rendered audio stands in for which demo take.  The names are invented;
# the sound is real output, so the waveform and the length are not a drawing.
TAKES = [
    dict(key="glasshouse-wide", lend="my-identity-wide-51b446d7cc9f",
         title="Glasshouse · Wide", kind="song", interpretation="wide",
         variety="bold", harmony=3, favourite=1, age=7 * HOUR, seed=108669884),
    dict(key="glasshouse-loose", lend="my-identity-loose-501ea61befcb",
         title="Glasshouse · Loose", kind="song", interpretation="loose",
         variety="bold", harmony=3, age=7 * HOUR, seed=108669884),
    dict(key="glasshouse-tight", lend="my-identity-tight-8245178386c5",
         title="Glasshouse · Tight", kind="song", interpretation="tight",
         variety="bold", harmony=3, age=7 * HOUR, seed=108669884),
    dict(key="glasshouse", lend="my-identity-settled-2c8ec83dbb37",
         title="Glasshouse", kind="song", interpretation="standard",
         variety="bold", harmony=3, favourite=1, age=7.5 * HOUR, seed=108669884,
         style_lora="chnsn_grand_boulevard.safetensors"),
    dict(key="blue-hour", lend="inst1-varied-1cc01e7f3cd4",
         title="Blue Hour", kind="instrumental", interpretation="tight",
         variety="varied", harmony=2, feel="steady", age=12 * HOUR, seed=108669884,
         style="synthwave, analog synth lead, arpeggios, gated drums, 112 BPM"),
    dict(key="paper-boats", lend="modern-girl-take1-8189c9bdab84",
         title="Paper Boats", kind="cover", interpretation="standard",
         variety="normal", harmony=1, age=13 * HOUR, seed=1448674792,
         source="demo-source",
         style="1960s psychedelic rock, jangly chime guitars, male vocal"),
    dict(key="copper-wire", lend="inst1-steady-d3962d6ad73a",
         title="Copper Wire", kind="instrumental", interpretation="settled",
         variety="normal", harmony=4, feel="steady", age=15 * HOUR, seed=417983998,
         style="downtempo, electric piano, upright bass, brushed drums, 88 BPM"),
    dict(key="tide-table", lend="inst1-wild-8eba8e68d33e",
         title="Tide Table", kind="instrumental", interpretation="settled",
         variety="varied", harmony=2, feel="steady", age=15.5 * HOUR, seed=2704334698,
         style="downtempo electronica, warm pads, uplifting, 92 BPM"),
    dict(key="night-drive", lend="modern-girl-original-4b277e4507e6",
         title="Night Drive", kind="cover", interpretation="standard",
         variety="normal", harmony=0, age=3 * 24 * HOUR, seed=3284668845,
         source="demo-source",
         style="English, synthwave, female vocal, analog pads, drum machine, 104 BPM"),
]

SONG_STYLE = "English, dream pop, female vocal, reverb guitars, soft bass, 104 BPM"

LYRICS = """[Verse]
Streetlights count us down the coast road
Radio low, the windows wide
Every mile a little quieter
Every mile a little kinder

[Chorus]
Hold the line, we are nearly home
Hold the line, we are nearly home

[Verse]
Glasshouse warm against the morning
Everything we grew still standing
Nothing here we need to carry
Nothing here we need to answer

[Chorus]
Hold the line, we are nearly home
Hold the line, we are nearly home

[Bridge]
Count the miles the way we used to
One more song and we are through

[Outro]
Hold the line
"""

# The recording a cover is made from.  The name is invented; the audio is a
# real file, so its waveform and length are real.
SOURCE = dict(id="demo-source", title="Paper Boats · rough mix",
              lend="3d1c0d2c3b9ee962-modern-girl-44-1k-clean.flac",
              filename="paper-boats-rough-mix.flac")

IDENTITY = dict(
    id="demovoice0001", name="Marlow Sands", trigger_word="marlowsands",
    description="warm indie pop, close lead vocal", voice="male",
    folder="/music/demo-voice", consent=1,
)
IDENTITY_SONGS = [
    ("Demo song 01", 236.4, "C major", 73), ("Demo song 02", 224.3, "E minor", 124),
    ("Demo song 03", 191.6, "D major", 148), ("Demo song 04", 161.2, "A major", 95),
    ("Demo song 05", 209.8, "D major", 83), ("Demo song 06", 173.4, "A major", 122),
    ("Demo song 07", 219.5, "Eb major", 79), ("Demo song 08", 135.7, "Bb major", 140),
    ("Demo song 09", 169.3, "A major", 69), ("Demo song 10", 209.1, "F major", 62),
]

# More corpora, for the Corpora screenshots.  Invented artists and songs, newest
# first; the first is the one shown opened, analysed, exported and trained.
KEYS = ["C major", "E minor", "D major", "A major", "Bb major", "G major", "F major", "Eb major", "B minor"]
CORPORA = [
    dict(id="glassorchard", name="Glass Orchard", trigger="glassorchard", voice="female",
         description="dream pop, chiming guitars, airy vocal", exported=True,
         lora="glass_orchard_lora.safetensors", age=2,
         songs=[("Lanternfish", 263.4), ("Salt Road", 221.0), ("The Long Quiet", 298.7),
                ("Paper Moons", 204.2), ("Weathervane", 246.9), ("Low Orbit", 311.5),
                ("Cinder Garden", 233.8), ("Harbour at Dusk", 279.1)]),
    dict(id="harbourlight", name="Harbour Lights", trigger="harbourlights", voice="male",
         description="folk rock, harmonica, acoustic guitar", exported=True, age=5, count=12),
    dict(id="junehalloway", name="June Halloway", trigger="junehalloway", voice="female",
         description="torch songs, piano, brushed drums", exported=True, age=9, count=16, left_out=2),
    dict(id="papercartogr", name="The Paper Cartographers", trigger="papercartographers", voice="male",
         description="power pop, crunchy guitars, harmonies", exported=True, age=14, count=10),
    dict(id="otisvane0001", name="Otis Vane", trigger="otisvane", voice="male",
         description="blues, slide guitar, gravel vocal", exported=True, age=20, count=9),
    dict(id="kestrelrow01", name="Kestrel Row", trigger="kestrelrow", voice="female",
         description="electronic, downtempo, breathy vocal", exported=False, age=26, count=17),
]
INVENTED = ["Northbound", "Tin Roof Rain", "Small Hours", "Copperline", "Dry Stone", "Blue Lantern",
            "Paper Wings", "Old Pier", "Second Light", "Wire and Wood", "Slow River", "Chalk Hill",
            "Nightjar", "Low Tide", "Ferris Wheel", "The Last Tram", "Stillwater"]


def link(src: Path, dst: Path) -> None:
    """Hard link where the filesystem allows it, copy where it does not."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def one_audio(folder: Path) -> Path:
    for f in sorted(folder.glob("*.flac")):
        return f
    raise SystemExit(f"no audio in {folder}")


def stand_ins(src: Path, wanted: list[str]) -> dict[str, Path]:
    """The take folder each demo take borrows from: its own when it is still in the
    library, otherwise another rendered take that has a score.  Only the sound is
    borrowed, for a real waveform and length; the names are the demo's."""
    spare = [d for d in sorted((src / "takes").iterdir())
             if (d / "take.json").exists() and any(d.glob("*.flac")) and d.name not in wanted
             and json.loads((d / "take.json").read_text()).get("score")]
    out = {}
    for name in wanted:
        if (src / "takes" / name).is_dir():
            out[name] = src / "takes" / name
        elif spare:
            out[name] = spare.pop(0)
        else:
            raise SystemExit(f"no rendered take to stand in for {name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="data", type=Path,
                    help="the library to borrow audio and a schema from")
    ap.add_argument("--to", dest="dst", required=True, type=Path,
                    help="the demo library to write (emptied first)")
    args = ap.parse_args()
    src, dst = args.src.resolve(), args.dst.resolve()
    if not (src / "yue2.sqlite").exists():
        raise SystemExit(f"no database at {src}")
    if dst == src:
        raise SystemExit("--to must not be the library it reads from")

    for name in ("takes", "sources", "stems", "identities", "personas", "tmp", "models"):
        shutil.rmtree(dst / name, ignore_errors=True)
    (dst / "tmp").mkdir(parents=True, exist_ok=True)
    (dst / "models").mkdir(parents=True, exist_ok=True)
    for stale in dst.glob("yue2.sqlite*"):
        stale.unlink()

    # The schema, taken from a real database so it is whatever the app expects
    # today, then emptied.  Settings come along, which is what a new install
    # would show anyway.
    db = dst / "yue2.sqlite"
    sqlite3.connect(src / "yue2.sqlite").backup(sqlite3.connect(db))
    con = sqlite3.connect(db)
    for table in ("takes", "sources", "stem_sets", "spaces", "identities", "identity_songs"):
        con.execute(f"DELETE FROM {table}")

    space = "demo00000001"
    con.execute("INSERT INTO spaces (id, name, created_at) VALUES (?,?,?)",
                (space, "Demo", NOW - 2 * 24 * HOUR))

    # The recording a cover is made from, with a score and lyrics already found,
    # so the form shows the state a cover actually starts from.
    lent = stand_ins(src, [spec["lend"] for spec in TAKES])
    borrowed = src / "sources" / SOURCE["lend"]
    stored = dst / "sources" / f"{SOURCE['id'][:16]}-{slug(Path(SOURCE['filename']).stem)}.flac"
    link(borrowed, stored)
    lend_abc = json.loads((lent[TAKES[5]["lend"]] / "take.json").read_text())
    con.execute(
        "INSERT INTO sources (id, title, filename, stored_path, sha256, created_at, abc,"
        " abc_updated_at, transcribe_state, lyrics, lyrics_state, duration)"
        " VALUES (?,?,?,?,?,?,?,?,'done',?, 'done', ?)",
        (SOURCE["id"], SOURCE["title"], SOURCE["filename"], f"/data/sources/{stored.name}",
         "0" * 64, NOW - 14 * HOUR, lend_abc.get("score"), NOW - 13.5 * HOUR,
         LYRICS, 208.8))

    for spec in TAKES:
        folder = lent[spec["lend"]]
        audio = one_audio(folder)
        note = json.loads((folder / "take.json").read_text())
        take_id = spec["key"].replace("-", "")[:12].ljust(12, "0")
        out = dst / "takes" / f"{slug(spec['title'])}-{take_id}"
        name = f"{slug(spec['title'])}.flac"
        link(audio, out / name)
        created = NOW - spec["age"]
        style = spec.get("style", SONG_STYLE)
        row = dict(
            id=take_id, kind=spec["kind"], source_id=spec.get("source"),
            title=spec["title"], style=style,
            lyrics="" if spec["kind"] == "instrumental" else LYRICS,
            abc=note.get("score"), mode="full", seed=spec["seed"],
            checkpoint="yue2_3b_bf16.safetensors", max_duration=240,
            status="done", audio_path=f"/data/takes/{out.name}/{name}",
            duration=note.get("duration"), favourite=spec.get("favourite", 0),
            created_at=created, finished_at=created + 300, elapsed=300,
            variety=spec.get("variety", "normal"), harmony=spec.get("harmony", 0),
            space_id=space, interpretation=spec["interpretation"],
            feel=spec.get("feel", "steady"), realaudio=1 if spec["kind"] == "song" else 0,
            identity_id=IDENTITY["id"] if spec["kind"] == "song" else None,
            style_lora=spec.get("style_lora"),
        )
        cols = ",".join(row)
        con.execute(f"INSERT INTO takes ({cols}) VALUES ({','.join('?' * len(row))})",
                    tuple(row.values()))
        (out / "take.json").write_text(json.dumps(
            {**note, "id": take_id, "title": spec["title"], "style": style,
             "lyrics": row["lyrics"], "seed": spec["seed"], "audio": name,
             "created_at": created}, indent=2))

    con.execute(
        "INSERT INTO identities (id, name, trigger_word, description, voice, folder,"
        " consent, created_at, exported_at, export_dir)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (IDENTITY["id"], IDENTITY["name"], IDENTITY["trigger_word"],
         IDENTITY["description"], IDENTITY["voice"], IDENTITY["folder"],
         IDENTITY["consent"], NOW - 30 * HOUR, NOW - 28 * HOUR,
         f"/data/identities/{IDENTITY['id']}/dataset"))
    for i, (title, length, key, tempo) in enumerate(IDENTITY_SONGS):
        con.execute(
            "INSERT INTO identity_songs (id, identity_id, file, title, sha256, duration,"
            " bit_rate, include, stored_path, vocals_state, score_state, lyrics_state,"
            " style_state, key, tempo, lyrics, style_hint, position)"
            " VALUES (?,?,?,?,?,?,?,1,?,'done','done','done','done',?,?,?,?,?)",
            (f"demosong{i:04d}", IDENTITY["id"], f"{slug(title)}.flac", title,
             f"{i:064d}", length, 320000,
             f"{IDENTITY['folder']}/{slug(title)}.flac", key, tempo,
             LYRICS, "indie pop, close vocal, acoustic guitar", i))

    for c in CORPORA:
        created = NOW - c["age"] * 24 * HOUR
        con.execute(
            "INSERT INTO identities (id, name, trigger_word, description, voice, folder,"
            " consent, created_at, exported_at, export_dir, lora) VALUES (?,?,?,?,?,?,1,?,?,?,?)",
            (c["id"], c["name"], c["trigger"], c["description"], c["voice"], f"/music/{c['name']}",
             created, created + 6 * HOUR if c["exported"] else None,
             f"/data/identities/{c['id']}/dataset" if c["exported"] else None, c.get("lora")))
        songs = c.get("songs") or [(INVENTED[i % len(INVENTED)], 190 + (i * 37) % 140) for i in range(c["count"])]
        for i, (title, length) in enumerate(songs):
            out = i >= len(songs) - c.get("left_out", 0)
            name = f"1-{i + 1:02d} {title}.flac"
            con.execute(
                "INSERT INTO identity_songs (id, identity_id, file, title, sha256, duration, bit_rate,"
                " include, flag, stored_path, vocals_state, score_state, lyrics_state, style_state,"
                " key, tempo, lyrics, style_hint, position)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'done','done','done','done',?,?,?,?,?)",
                (f"{c['id'][:8]}{i:04d}", c["id"], name, title, f"{c['id']}{i:04d}".ljust(64, "0"),
                 71.0 if out else length, 900000, 0 if out else 1, "shorter than 90 seconds" if out else None,
                 f"/music/{c['name']}/{name}", KEYS[(i * 5) % len(KEYS)], 68 + (i * 29) % 90,
                 LYRICS, c["description"], i))

    con.commit()
    con.close()
    print(f"demo library written to {dst}")
    print(f"  {len(TAKES)} takes in the Demo space, 1 recording, "
          f"1 Identity of {len(IDENTITY_SONGS)} songs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
