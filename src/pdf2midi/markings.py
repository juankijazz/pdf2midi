"""Lectura de tempo y matices con un modelo de visión local y aplicación al MIDI.

Los modelos de visión locales NO leen bien las notas del pentagrama, pero sí el texto
impreso (Andante ♩=88, p, mf, rit., a tempo, calderón…). El OMR (homr) no lee ese texto,
así que lo pedimos al modelo y lo aplicamos al MIDI: tempo, ritardandos, calderones y
dinámicas. Si el modelo falla o contesta algo raro, se ignora sin romper la conversión.
"""
from __future__ import annotations

from .llm import LLMError, VisionClient
from .musicxml2midi import DYN, Score

SYSTEM = ("You are an expert music-score reader. You only read the PRINTED TEXT AND SYMBOLS that are "
          "not notes: tempo marks, dynamics, tempo changes. You answer with a single JSON object and nothing else.")

PROMPT = """This is page {page} of a piano score. Its measures are numbered {first} to {last} ({n} measures in total).
Printed measure numbers appear at the start of each system; use them.

Return ONLY this JSON (no commentary):
{{"tempo_bpm": <number or null>,
  "markings": [
    {{"measure": <int>, "type": "<dynamic|cresc|dim|rit|a_tempo|fermata|tempo>", "value": "<see below>", "end_measure": <int, optional>}}
  ]}}

Rules:
- "tempo_bpm": quarter-note beats per minute if the page shows a metronome mark such as (quarter = 88); else null.
- type "dynamic": value is one of ppp, pp, p, mp, mf, f, ff, fff, sf, sfz (measure where it is written).
- type "cresc" / "dim": crescendo / diminuendo (hairpin or text); give measure and end_measure.
- type "rit": ritardando / rall.; give measure and end_measure (last measure it applies to).
- type "a_tempo": 'a tempo' or 'Tempo I' (return to the original speed) at that measure.
- type "tempo": a new metronome mark in the middle of the page; value is the bpm number.
- type "fermata": a fermata over that measure.
- Only include what you can clearly read. Use measure numbers between {first} and {last}. If unsure, leave it out."""


def _int(x):
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def extract_markings(client: VisionClient, image_path: str, page: int, first: int, n_measures: int) -> dict:
    last = first + max(n_measures, 1) - 1
    raw = client.chat_json(SYSTEM, PROMPT.format(page=page, first=first, last=last, n=n_measures), image_path)
    out = {"tempo_bpm": None, "markings": []}
    bpm = _int(raw.get("tempo_bpm")) if isinstance(raw, dict) else None
    if bpm and 30 <= bpm <= 240:
        out["tempo_bpm"] = bpm
    for m in (raw.get("markings") or []) if isinstance(raw, dict) else []:
        if not isinstance(m, dict):
            continue
        t = str(m.get("type", "")).lower().strip()
        meas = _int(m.get("measure"))
        if t not in {"dynamic", "cresc", "dim", "rit", "a_tempo", "fermata", "tempo"} or meas is None:
            continue
        if not (first <= meas <= last):
            continue
        item = {"type": t, "measure": meas}
        end = _int(m.get("end_measure"))
        item["end_measure"] = min(max(end, meas), last) if end is not None else meas
        v = str(m.get("value", "")).lower().strip()
        if t == "dynamic":
            if v not in DYN:
                continue
            item["value"] = v
        elif t == "tempo":
            b = _int(v)
            if not b or not 30 <= b <= 240:
                continue
            item["value"] = b
        out["markings"].append(item)
    return out


def apply_markings(score: Score, markings: list, base_bpm: float) -> list[str]:
    """Modifica score.tempos y las velocidades. Devuelve un resumen legible."""
    notes_log = []
    ms = list(score.measures) + [score.length]

    def start(m):   # compás (1-based) -> beat
        return ms[m - 1] if 1 <= m <= len(score.measures) else None

    def end(m):
        return ms[m] if 1 <= m <= len(score.measures) else None

    tempos = [(0.0, float(base_bpm))]
    vel_events = []     # (beat, vel)
    ramps = []          # (b0, b1, delta_vel)
    cur = float(base_bpm)
    for mk in sorted(markings, key=lambda x: (x["measure"], x["type"])):
        t, m = mk["type"], mk["measure"]
        b0 = start(m)
        if b0 is None:
            continue
        if t == "tempo":
            cur = float(mk["value"]); tempos.append((b0, cur)); notes_log.append(f"c.{m}: tempo {int(cur)}")
        elif t == "a_tempo":
            tempos.append((b0, float(base_bpm))); cur = float(base_bpm); notes_log.append(f"c.{m}: a tempo")
        elif t == "rit":
            b1 = end(mk["end_measure"]) or end(m)
            steps = max(2, int(b1 - b0))
            for i in range(steps):
                tempos.append((b0 + (b1 - b0) * i / steps, cur * (1 - 0.30 * (i + 1) / steps)))
            notes_log.append(f"c.{m}-{mk['end_measure']}: rit.")
        elif t == "fermata":
            e = end(m)
            tempos.append((e - 2.0, cur * 0.5)); tempos.append((e, cur)); notes_log.append(f"c.{m}: calderón")
        elif t == "dynamic":
            vel_events.append((b0, DYN[mk["value"]])); notes_log.append(f"c.{m}: {mk['value']}")
        elif t in ("cresc", "dim"):
            b1 = end(mk["end_measure"]) or end(m)
            ramps.append((b0, b1, 22 if t == "cresc" else -22)); notes_log.append(f"c.{m}-{mk['end_measure']}: {t}.")
    # tempo: un solo valor por posición (el último gana), ordenado
    d = {}
    for b, v in tempos:
        d[round(b, 4)] = v
    score.tempos = sorted(d.items())
    # velocidades
    vel_events.sort()
    if vel_events or ramps:
        for n in score.notes:
            v = None
            for b, vel in vel_events:
                if b <= n.start + 1e-6:
                    v = vel
                else:
                    break
            if v is None:
                v, boost = n.vel, 0          # ya incluye acento si lo había
            else:
                boost = 16 if n.accent else 0
            for b0, b1, dv in ramps:
                if b0 <= n.start < b1:
                    v += dv * (n.start - b0) / max(b1 - b0, 1e-6)
            n.vel = int(max(20, min(125, v + boost)))
    return notes_log
