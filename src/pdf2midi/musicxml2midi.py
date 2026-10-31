"""Convertidor MusicXML -> MIDI (sin dependencias pesadas, solo mido).

Soporta: varias partes/pentagramas, acordes, ligaduras de unión, silencios,
backup/forward, notas de adorno (cortas), tresillos (la duración ya viene
resuelta en <duration>), alteraciones explícitas, tempo (<sound tempo>),
dinámicas (pp..ff) y articulaciones básicas (staccato / acento).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import mido

TPB = 480
STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DYN = {"ppp": 28, "pp": 40, "p": 52, "mp": 64, "mf": 76, "f": 92, "ff": 108, "fff": 120,
       "sf": 100, "sfz": 100, "fp": 90, "rfz": 100}
DEFAULT_VEL = 64


@dataclass
class Note:
    start: float           # en negras
    dur: float
    pitch: int
    track: int             # 0 = pentagrama superior, 1 = inferior, ...
    vel: int = DEFAULT_VEL
    accent: bool = False
    staccato: bool = False
    grace: bool = False


@dataclass
class Score:
    notes: list = field(default_factory=list)
    tempos: list = field(default_factory=list)      # (beat, bpm)
    measures: list = field(default_factory=list)    # beats de inicio de compás
    length: float = 0.0


def _strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _pitch(note_el):
    p = note_el.find("pitch")
    if p is None:
        return None
    step = p.findtext("step")
    octave = int(p.findtext("octave"))
    alter = p.findtext("alter")
    alter = int(round(float(alter))) if alter not in (None, "") else 0
    return 12 * (octave + 1) + STEP[step] + alter


def parse_musicxml(path: str) -> Score:
    root = _strip_ns(ET.parse(path).getroot())
    sc = Score()
    track_base = 0
    for part in root.findall("part"):
        divisions = 1
        cursor = 0.0
        nstaves = 1
        expected = 4.0
        dyn_events = []            # (beat, vel)
        part_notes = []            # en orden de creación
        pending_grace = []
        last_start = 0.0
        measures = part.findall("measure")
        for mi, meas in enumerate(measures):
            m_start = cursor
            m_end = cursor
            sc.measures.append(m_start)
            m_notes = []           # (Note, voice, tie_start, tie_stop)
            voice_end: dict = {}
            for el in list(meas):
                tag = el.tag
                if tag == "attributes":
                    d = el.findtext("divisions")
                    if d:
                        divisions = max(1, int(float(d)))
                    st = el.findtext("staves")
                    if st:
                        nstaves = max(nstaves, int(st))
                    b, bt = el.findtext("time/beats"), el.findtext("time/beat-type")
                    if b and bt and b.isdigit() and bt.isdigit():
                        expected = int(b) * 4.0 / int(bt)
                elif tag == "direction":
                    snd = el.find("sound")
                    if snd is not None and snd.get("tempo"):
                        sc.tempos.append((cursor, float(snd.get("tempo"))))
                    dyn = el.find(".//dynamics")
                    if dyn is not None:
                        for child in dyn:
                            if child.tag in DYN:
                                dyn_events.append((cursor, DYN[child.tag]))
                                break
                elif tag == "sound" and el.get("tempo"):
                    sc.tempos.append((cursor, float(el.get("tempo"))))
                elif tag == "backup":
                    cursor -= int(float(el.findtext("duration") or 0)) / divisions
                elif tag == "forward":
                    cursor += int(float(el.findtext("duration") or 0)) / divisions
                    m_end = max(m_end, cursor)
                elif tag == "note":
                    is_chord = el.find("chord") is not None
                    is_grace = el.find("grace") is not None
                    is_rest = el.find("rest") is not None
                    dur_txt = el.findtext("duration")
                    dur = (int(float(dur_txt)) / divisions) if dur_txt else 0.0
                    staff = int(el.findtext("staff") or 1) - 1
                    voice = (staff, el.findtext("voice") or "1")
                    start = last_start if is_chord else cursor
                    if not is_rest:
                        midi = _pitch(el)
                        if midi is not None:
                            trk = track_base + staff
                            tie_stop = any(t.get("type") == "stop" for t in el.findall("tie"))
                            tie_start = any(t.get("type") == "start" for t in el.findall("tie"))
                            art = el.find("notations/articulations")
                            accent = art is not None and (art.find("accent") is not None or art.find("strong-accent") is not None)
                            stacc = art is not None and (art.find("staccato") is not None or art.find("staccatissimo") is not None)
                            n = Note(start, 0.06 if is_grace else dur, midi, trk, accent=accent,
                                     staccato=stacc, grace=is_grace)
                            m_notes.append((n, voice, tie_start, tie_stop))
                            if is_grace:
                                pending_grace.append(n)
                            else:
                                for g in pending_grace:
                                    g.start = max(0.0, start - 0.06 * len(pending_grace))
                                pending_grace = []
                    if not is_chord:
                        last_start = cursor
                        if not is_grace:
                            cursor += dur
                    if not is_grace:
                        voice_end[voice] = max(voice_end.get(voice, m_start), cursor)
                    m_end = max(m_end, cursor)
            # ---- reparación rítmica: cada voz debe caber en el compás ----
            longest = max(voice_end.values(), default=m_start) - m_start
            for n, voice, _, _ in m_notes:
                v_len = voice_end.get(voice, m_start) - m_start
                if v_len > expected + 0.01:
                    f = expected / v_len
                    n.start = m_start + (n.start - m_start) * f
                    if not n.grace:
                        n.dur *= f
            first_or_last = mi == 0 or mi == len(measures) - 1
            if longest > expected + 0.01 or (longest < expected - 0.01 and not first_or_last):
                cursor = m_start + expected
            else:
                cursor = m_start + longest
            part_notes.extend(m_notes)

        # ---- ligaduras de unión ----
        open_ties: dict = {}
        final = []
        for n, _, tie_start, tie_stop in part_notes:
            key = (n.track, n.pitch)
            if tie_stop and key in open_ties:
                o = open_ties[key]
                o.dur = (n.start + n.dur) - o.start
                if not tie_start:
                    del open_ties[key]
                continue
            final.append(n)
            if tie_start:
                open_ties[key] = n
        # ---- dinámicas -> velocidades ----
        dyn_events.sort()
        for n in final:
            v = DEFAULT_VEL
            for b, vel in dyn_events:
                if b <= n.start + 1e-6:
                    v = vel
                else:
                    break
            if n.accent:
                v = min(127, v + 16)
            if n.grace:
                v = max(20, v - 8)
            n.vel = v
        sc.notes.extend(final)
        sc.length = max(sc.length, cursor)
        track_base += nstaves
    sc.tempos.sort()
    return sc


def merge_scores(scores: list) -> Score:
    """Concatena varias páginas una detrás de otra."""
    out = Score()
    offset = 0.0
    for s in scores:
        for n in s.notes:
            out.notes.append(Note(n.start + offset, n.dur, n.pitch, n.track, n.vel, n.accent, n.staccato, n.grace))
        out.tempos += [(b + offset, t) for b, t in s.tempos]
        out.measures += [m + offset for m in s.measures]
        offset += s.length
    out.length = offset
    return out


def write_midi(score: Score, path: str, bpm: float = 90.0, pedal: bool = False) -> None:
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    tempo_track = mido.MidiTrack()
    mid.tracks.append(tempo_track)
    tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    tempo_track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    tempos = score.tempos or [(0.0, bpm)]
    if tempos[0][0] > 0:
        tempos = [(0.0, tempos[0][1])] + tempos
    last = 0
    for b, t in tempos:
        tick = int(round(b * TPB))
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=int(60e6 / t), time=tick - last))
        last = tick

    ntracks = max((n.track for n in score.notes), default=0) + 1
    names = ["Mano derecha", "Mano izquierda"]
    for t in range(ntracks):
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=names[t] if t < 2 else f"Pentagrama {t+1}", time=0))
        tr.append(mido.Message("program_change", program=0, channel=0, time=0))
        ev = []
        for n in score.notes:
            if n.track != t:
                continue
            d = n.dur * (0.5 if n.staccato else 0.97)
            s = int(round(n.start * TPB))
            e = max(s + 1, int(round((n.start + d) * TPB)))
            ev.append((s, 1, "note_on", n.pitch, n.vel))
            ev.append((e, 0, "note_off", n.pitch, 0))
        if pedal and t == ntracks - 1:
            ms = sorted(set(score.measures)) + [score.length]
            for a, b in zip(ms, ms[1:]):
                ev.append((int(round(a * TPB)), 2, "control_change", 64, 127))
                ev.append((int(round((b - 0.06) * TPB)), 0, "control_change", 64, 0))
        ev.sort(key=lambda x: (x[0], x[1]))
        last = 0
        for tick, _, kind, a, b in ev:
            if kind == "control_change":
                tr.append(mido.Message(kind, control=a, value=b, channel=0, time=tick - last))
            else:
                tr.append(mido.Message(kind, note=a, velocity=b, channel=0, time=tick - last))
            last = tick
    mid.save(path)
