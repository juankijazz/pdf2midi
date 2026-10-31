"""Compara la salida de varios motores OMR con un MIDI de referencia.

Uso:
  python tools/compare_omr.py REFERENCIA.mid  nombre=fichero  nombre2=pag1.musicxml+pag2.musicxml+pag3.musicxml ...

Formatos de candidato: .mid, .musicxml/.xml/.mxl, .abc (Legato), .krn (Transcoda / SMT).
'+' une varias páginas una detrás de otra. Mide, nota a nota, si coinciden (negra, altura) con la referencia.
La referencia NO es una verdad absoluta (es una transcripción manual): sirve para comparar motores entre sí.
"""
import collections
import math
import sys
from pathlib import Path


def notes_from_midi(path):
    import mido
    mid = mido.MidiFile(path)
    out, length = [], 0.0
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0:
                out.append((t / mid.ticks_per_beat, m.note))
                length = max(length, t / mid.ticks_per_beat)
    return out, length


def notes_from_xml(path):
    """MusicXML con la misma reparación rítmica que usa PDF2MIDI (compases de 4 negras bien cerrados)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from pdf2midi.musicxml2midi import parse_musicxml
    sc = parse_musicxml(path)
    return [(n.start, n.pitch) for n in sc.notes if not n.grace], sc.length


def notes_from_m21(path):
    """ABC (Legato) o **kern (Transcoda/SMT): se pasa a MusicXML con music21 y se lee igual que homr."""
    import tempfile
    from music21 import converter
    s = converter.parse(path)
    tmp = tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False)
    tmp.close()
    s.write("musicxml", fp=tmp.name)
    return notes_from_xml(tmp.name)


def load(spec):
    notes, offset = [], 0.0
    for part in spec.split("+"):
        ext = Path(part).suffix.lower()
        if ext in (".mid", ".midi"):
            n, length = notes_from_midi(part)
        elif ext in (".musicxml", ".xml"):
            n, length = notes_from_xml(part)
        else:
            n, length = notes_from_m21(part)
        notes += [(b + offset, p) for b, p in n]
        offset += math.ceil(length / 4.0) * 4.0
    return notes, offset


def beatsets(notes):
    d = collections.defaultdict(set)
    for b, p in notes:
        d[int(b + 1e-6)].add(p)
    return d


def f1(ref, cand, lo, hi):
    tp = sum(len(ref.get(b, set()) & cand.get(b, set())) for b in range(lo, hi))
    nr = sum(len(ref.get(b, set())) for b in range(lo, hi))
    nc = sum(len(cand.get(b, set())) for b in range(lo, hi))
    if nr == 0 and nc == 0:
        return 1.0, 1.0, 1.0
    r, p = tp / max(nr, 1), tp / max(nc, 1)
    return r, p, (2 * r * p / (r + p) if r + p else 0.0)


def hist_cos(a, b):
    ha, hb = collections.Counter(p for _, p in a), collections.Counter(p for _, p in b)
    dot = sum(ha[k] * hb[k] for k in ha)
    na = math.sqrt(sum(v * v for v in ha.values())); nb = math.sqrt(sum(v * v for v in hb.values()))
    return dot / (na * nb) if na and nb else 0.0


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    ref_notes, ref_len = load(sys.argv[1])
    ref = beatsets(ref_notes)
    total = int(ref_len)
    print(f"Referencia: {len(ref_notes)} notas, {ref_len:.0f} negras\n")
    print(f"{'motor':<14}{'notas':>7}{'negras':>8}{'F1 total':>10}{'F1 1/3':>8}{'F1 2/3':>8}{'F1 3/3':>8}{'cos.alturas':>13}")
    for arg in sys.argv[2:]:
        name, _, spec = arg.partition("=")
        try:
            notes, length = load(spec)
        except Exception as e:
            print(f"{name:<14}  ERROR: {e}"); continue
        c = beatsets(notes)
        t1, t2 = total // 3, 2 * total // 3
        row = [f1(ref, c, 0, total)[2], f1(ref, c, 0, t1)[2], f1(ref, c, t1, t2)[2], f1(ref, c, t2, total)[2]]
        print(f"{name:<14}{len(notes):>7}{length:>8.0f}" + "".join(f"{x:>8.2f}" if i else f"{x:>10.2f}" for i, x in enumerate(row))
              + f"{hist_cos(ref_notes, notes):>13.3f}")
    print("\nF1 = acierto nota a nota (misma negra y misma altura). 'negras' distintas de la referencia "
          "indican compases de más o de menos, que desplazan el resto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
