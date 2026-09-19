"""YuE2 Studio: a harmony control for YuE2 score plans.

YuE2's planner tends to write one four-chord loop and use it for every section.
The stock repetition penalty cannot fix that: it pushes against every recent token,
bar lines and section names included, and breaks the score long before the chords
change.  This node pushes against recently used chords only.

While the planner writes a chord symbol ("Cmaj7"), candidate tokens that would
spell a recently used chord lose logits in proportion to that chord's share of
recent chord changes.  Holding the current chord is free up to a limit, so the
model keeps its own harmonic rhythm; past the limit, staying on the same root costs
more with every bar, so the song cannot settle on one chord.  Two ways to name "the
same chord":

  spelling  exact symbols.  Cmaj7 and C are different, so the model is free to
            recolour a chord; the result stays in the key.
  root      root pitch class.  C, Cmaj7 and C/E are one chord, so the model has
            to move somewhere new, and borrowed chords appear.

An optional bonus favours roots outside the key from the score's K: line, only on
a change of chord and only while few recent chords are already outside, so the
song cannot settle on an out-of-key chord.

The node wraps comfy.text_encoders.yue2.distribution for the length of one
generation and restores it afterwards.  With strength 0 and no bonus, its output is
identical to the stock YuE2 Generate ABC node.
"""
import collections
import contextlib
import re

import comfy.text_encoders.yue2 as yue2

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
HEADER = re.compile(r"^[A-Za-z]:")
KEY_LINE = re.compile(r"^K:\s*([A-G][#b]?)(m?)", re.M)
MAJOR_STEPS = {0, 2, 4, 5, 7, 9, 11}
MINOR_STEPS = {0, 2, 3, 5, 7, 8, 10}
_VOCAB = {}


def root_of(text):
    """Pitch class of a chord's root, or None.  A lone letter counts as the natural."""
    if not text or text[0] not in NOTE:
        return None
    pc = NOTE[text[0]]
    if text[1:2] == "#":
        pc += 1
    elif text[1:2] == "b":
        pc -= 1
    return pc % 12


def vocabulary(clip):
    """Decoded text of every ABC-phase token, computed once per tokenizer."""
    raw = clip.tokenizer.tokenizer
    if id(raw) not in _VOCAB:
        _VOCAB.clear()
        _VOCAB[id(raw)] = raw.decode_batch([[i] for i in range(yue2.EOD)], skip_special_tokens=False)
    return _VOCAB[id(raw)]


def walk(text, line, partial):
    """Advance the chord-symbol state over text.  Quotes on header lines (V: name="...")
    are not chords.  Returns (line, partial, completed symbols)."""
    done = []
    for ch in text:
        if ch == "\n":
            line, partial = "", None
            continue
        if partial is None:
            if ch == '"' and not HEADER.match(line):
                partial = ""
        elif ch == '"':
            done.append(partial)
            partial = None
        else:
            partial += ch
        line += ch
    return line, partial, done


class HarmonyTracker:
    def __init__(self, vocab, mode="root", strength=0.0, window=16, hold_limit=8,
                 outside_bonus=0.0, outside_limit=0.25, candidates=64):
        self.vocab = vocab
        self.mode = mode
        self.strength = strength
        self.hold_limit = hold_limit
        self.outside_bonus = outside_bonus if mode == "root" else 0.0
        self.outside_limit = outside_limit
        self.candidates = candidates
        self.seen = 0
        self.line = ""
        self.partial = None
        self.changes = collections.deque(maxlen=window)
        self.held = 0            # consecutive chord symbols on the same root, in either mode
        self.last_root = None
        self.head = ""
        self.scale = None
        self.chord_starts = [i for i, t in enumerate(vocab) if t.startswith('"') and t[1:2] in NOTE]

    @property
    def active(self):
        return self.strength > 0 or self.outside_bonus > 0

    # ------------------------------------------------------------- following
    def identity(self, symbol):
        return root_of(symbol) if self.mode == "root" else symbol

    def feed(self, history):
        for token in history[self.seen:]:
            text = self.vocab[token] if token < len(self.vocab) else ""
            if self.scale is None and self.mode == "root":
                self.head += text
                key = KEY_LINE.search(self.head)
                if key and "\n" in self.head[key.end():]:
                    steps = MINOR_STEPS if key.group(2) else MAJOR_STEPS
                    self.scale = {(root_of(key.group(1)) + s) % 12 for s in steps}
            self.line, self.partial, done = walk(text, self.line, self.partial)
            for symbol in done:
                root = root_of(symbol)
                if root is None:
                    continue
                # Holding is counted by root, so respelling a chord (E5, Em, Em7)
                # does not reset the count.
                if root == self.last_root:
                    self.held += 1
                else:
                    self.last_root = root
                    self.held = 1
                ident = self.identity(symbol)
                if not self.changes or self.changes[-1] != ident:
                    self.changes.append(ident)
        self.seen = len(history)

    def outside_share(self):
        if not self.scale or not self.changes:
            return 0.0
        return sum(1 for r in self.changes if r not in self.scale) / len(self.changes)

    # --------------------------------------------------------------- scoring
    def spelling_penalty(self, completed, partial):
        current = self.changes[-1]
        counts = collections.Counter(self.changes)
        total = len(self.changes)
        score = 0.0
        for symbol in completed:
            if root_of(symbol) is not None and symbol != current:
                score += counts[symbol] / total
        if partial and root_of(partial) is not None and not current.startswith(partial):
            score += sum(n for c, n in counts.items() if c.startswith(partial) and c != current) / total
        return self.strength * score

    def hold_penalty(self, root):
        if self.hold_limit and root == self.last_root and self.held >= self.hold_limit:
            return self.strength * (1 + self.held - self.hold_limit) / 4
        return 0.0

    def root_penalty(self, root):
        current = self.changes[-1]
        value = 0.0
        if root == current:
            return self.hold_penalty(root)
        value += self.strength * collections.Counter(self.changes)[root] / len(self.changes)
        if (self.outside_bonus and self.scale is not None and root not in self.scale
                and self.outside_share() < self.outside_limit):
            value -= self.outside_bonus
        return value

    def bias(self, logits):
        """Logit adjustments for this step, as (ids, values).  Only the top candidates
        are scored: a penalty only lowers a token, so one outside them could not be
        sampled either way.  A bonus can raise one, so chord openings are added."""
        if not self.active or not self.changes:
            return None
        top = logits[0, :yue2.EOD].topk(self.candidates).indices.tolist()
        if self.outside_bonus and self.partial is None and any('"' in self.vocab[t] for t in top):
            top = list(dict.fromkeys(top + self.chord_starts))
        before = self.partial or ""
        out_ids, values = [], []
        for token in top:
            text = self.vocab[token]
            if self.partial is None and '"' not in text:
                continue
            _, partial, done = walk(text, self.line, self.partial)
            if self.mode == "spelling":
                if not done and not partial:
                    continue
                value = self.spelling_penalty(done, partial)
                symbol = done[0] if done else partial
                if len(before) <= 1 and root_of(symbol) is not None:
                    value += self.hold_penalty(root_of(symbol))
            else:
                symbol = done[0] if done else partial
                # The root is decided at its letter, and at the step after it, where
                # an accidental or anything else settles sharp, flat or natural.
                if not symbol or root_of(symbol) is None or len(before) >= 2:
                    continue
                value = self.root_penalty(root_of(symbol))
            if value:
                out_ids.append(token)
                values.append(value)
        return (out_ids, values) if out_ids else None


@contextlib.contextmanager
def steering(tracker):
    import torch

    original = yue2.distribution

    def distribution(logits, history, step, phase, *args, **kwargs):
        if phase == "abc":
            tracker.feed(history)
            adjust = tracker.bias(logits)
            if adjust:
                logits = logits.clone()
                ids = torch.tensor(adjust[0], device=logits.device, dtype=torch.long)
                logits[..., ids] -= torch.tensor(adjust[1], device=logits.device, dtype=logits.dtype)
        return original(logits, history, step, phase, *args, **kwargs)

    yue2.distribution = distribution
    try:
        yield
    finally:
        yue2.distribution = original


class YuE2GenerateABCHarmony:
    CATEGORY = "model/conditioning/yue2"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("abc",)
    FUNCTION = "execute"
    DESCRIPTION = "YuE2 Generate ABC with control over how predictable the chord progression is."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": ("CLIP",),
            "style": ("STRING", {"multiline": True}),
            "lyrics": ("STRING", {"multiline": True}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "mode": (["full", "melody"],),
            "max_abc_tokens": ("INT", {"default": 8192, "min": 1, "max": 20000}),
            "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 5.0, "step": 0.05}),
            "top_p": ("FLOAT", {"default": 0.9, "min": 0.01, "max": 1.0, "step": 0.01}),
            "top_k": ("INT", {"default": 30, "min": 1, "max": 32768}),
            "repetition_penalty": ("FLOAT", {"default": 1.005, "min": 0.01, "max": 10.0, "step": 0.005}),
            "penalty_window": ("INT", {"default": 100, "min": 1, "max": 20000}),
            "chord_identity": (["root", "spelling"], {"tooltip": "root: C, Cmaj7 and C/E count as one chord. spelling: exact symbols."}),
            "chord_strength": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 64.0, "step": 0.5,
                                         "tooltip": "Logits taken from a chord for its share of recent chord changes. 0 is off."}),
            "chord_window": ("INT", {"default": 16, "min": 1, "max": 512, "tooltip": "Recent chord changes remembered."}),
            "hold_limit": ("INT", {"default": 8, "min": 0, "max": 64, "tooltip": "Bars one root may hold before staying on it costs. 0 is no limit."}),
            "outside_bonus": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 20.0, "step": 0.5,
                                        "tooltip": "Root mode: logits added to a change to a root outside the key."}),
            "outside_limit": ("FLOAT", {"default": 0.25, "min": 0.0, "max": 1.0, "step": 0.05,
                                        "tooltip": "The bonus stops while this share of recent chords is already outside the key."}),
        }}

    def execute(self, clip, style, lyrics, seed, mode, max_abc_tokens, temperature, top_p, top_k, repetition_penalty,
                penalty_window, chord_identity, chord_strength, chord_window, hold_limit, outside_bonus, outside_limit):
        tokens = clip.tokenize(style, lyrics=lyrics, cot=mode, seed=seed, max_tokens=max_abc_tokens, penalty_window=penalty_window)
        tracker = HarmonyTracker(vocabulary(clip), chord_identity, chord_strength, chord_window, hold_limit,
                                 outside_bonus, outside_limit, candidates=max(64, top_k))
        generate = lambda: clip.generate(tokens, max_length=max_abc_tokens, temperature=temperature, top_p=top_p,
                                         top_k=top_k, repetition_penalty=repetition_penalty, seed=seed)
        if tracker.active:
            with steering(tracker):
                ids = generate()
        else:
            ids = generate()
        return (clip.decode(ids),)


NODE_CLASS_MAPPINGS = {"YuE2GenerateABCHarmony": YuE2GenerateABCHarmony}
NODE_DISPLAY_NAME_MAPPINGS = {"YuE2GenerateABCHarmony": "YuE2 Generate ABC (harmony)"}
