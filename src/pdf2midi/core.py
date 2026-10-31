"""Núcleo: PDF (imagen o vectorial) -> páginas -> OMR (homr) -> MusicXML -> MIDI."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, Optional

from .musicxml2midi import Score, merge_scores, parse_musicxml, write_midi

LogFn = Callable[[str], None]


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- homr
_homr = None


def _load_homr():
    """Carga homr una sola vez, sin OCR de títulos (no hace falta para el MIDI)."""
    global _homr
    if _homr is not None:
        return _homr
    # homr importa rapidocr solo para leer el título de la partitura. No lo
    # necesitamos: lo sustituimos por un módulo vacío (ahorra ~100 MB y tiempo).
    if "rapidocr" not in sys.modules:
        fake = types.ModuleType("rapidocr")

        class RapidOCR:  # pragma: no cover
            def __call__(self, *a, **k):
                raise RuntimeError("OCR desactivado")

        fake.RapidOCR = RapidOCR
        sys.modules["rapidocr"] = fake

    from homr import main as hm  # noqa: E402

    def _no_title(debug, staff):
        f: Future = Future()
        f.set_result("")
        return f

    hm.detect_title = _no_title
    try:
        import onnxruntime as ort
        ort.set_default_logger_severity(3)
    except Exception:
        pass
    _homr = hm
    return hm


def _check_models(hm) -> None:
    from homr.transformer.configs import default_config
    from homr.segmentation.config import segnet_path_onnx
    missing = [p for p in (segnet_path_onnx, default_config.filepaths.encoder_path,
                           default_config.filepaths.decoder_path) if not os.path.exists(p)]
    if missing:
        # Solo ocurre al ejecutar desde código fuente sin haber descargado modelos.
        hm.download_weights(False, False, False)


def omr_image(image_path: str, bpm: Optional[int] = None) -> str:
    """Reconoce una imagen de partitura y devuelve la ruta del .musicxml generado."""
    hm = _load_homr()
    _check_models(hm)
    from homr.music_xml_generator import XmlGeneratorArguments

    cfg = hm.ProcessingConfig(False, False, False, False, -1, False, False, False)
    args = XmlGeneratorArguments(False, None, bpm)
    hm.process_image(image_path, cfg, args)
    return os.path.splitext(image_path)[0] + ".musicxml"


# ---------------------------------------------------------------- PDF
def render_pdf(pdf_path: str, out_dir: str, dpi: int = 200, max_pages: int = 200) -> list[str]:
    """Renderiza cada página del PDF a PNG (sirve para PDF escaneado o vectorial)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_path)
    paths = []
    try:
        n = min(len(pdf), max_pages)
        for i in range(n):
            page = pdf[i]
            w, h = page.get_size()
            scale = dpi / 72.0
            # límite de seguridad para páginas enormes
            scale = min(scale, 4500.0 / max(w, h))
            bmp = page.render(scale=scale)
            img = bmp.to_pil().convert("RGB")
            p = os.path.join(out_dir, f"pagina_{i + 1:03d}.png")
            img.save(p)
            paths.append(p)
            page.close()
    finally:
        pdf.close()
    return paths


def _ascii_tempdir() -> str:
    """OpenCV en Windows no abre rutas con tildes/ñ: si la carpeta temporal las tiene, usa otra."""
    base = tempfile.gettempdir()
    if base.isascii():
        return tempfile.mkdtemp(prefix="pdf2midi_")
    for cand in (os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "pdf2midi_tmp"),
                 os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "pdf2midi_tmp")):
        try:
            os.makedirs(cand, exist_ok=True)
            return tempfile.mkdtemp(prefix="p_", dir=cand)
        except OSError:
            continue
    return tempfile.mkdtemp(prefix="pdf2midi_")


# ---------------------------------------------------------------- conversión
def convert_pdf(
    pdf_path: str | Path,
    out_dir: str | Path,
    bpm: float = 90.0,
    pedal: bool = False,
    keep_musicxml: bool = True,
    log: LogFn = print,
    progress: Optional[Callable[[float], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> Path:
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = pdf_path.stem
    tmp = _ascii_tempdir()
    try:
        log(f"► {pdf_path.name}: preparando páginas…")
        pages = render_pdf(str(pdf_path), tmp)
        if not pages:
            raise RuntimeError("El PDF no tiene páginas.")
        log(f"  {len(pages)} página(s). Reconociendo partitura (puede tardar ~1 min por página)…")
        scores: list[Score] = []
        for i, img in enumerate(pages, 1):
            if cancel and cancel():
                raise Cancelled()
            if progress:
                progress((i - 1) / len(pages))
            log(f"  Página {i}/{len(pages)}…")
            try:
                xml = omr_image(img, int(bpm))
            except Exception as e:  # página sin música, ilegible, etc.
                log(f"  ⚠ Página {i} omitida: {e}")
                continue
            sc = parse_musicxml(xml)
            if not sc.notes:
                log(f"  ⚠ Página {i}: no se encontraron notas.")
                continue
            scores.append(sc)
            log(f"  ✓ Página {i}: {len(sc.notes)} notas")
            if keep_musicxml:
                shutil.copyfile(xml, out_dir / f"{name}_pagina{i}.musicxml")
        if not scores:
            raise RuntimeError("No se pudo reconocer ninguna nota en el PDF.")
        total = merge_scores(scores)
        out = out_dir / f"{name}.mid"
        write_midi(total, str(out), bpm=bpm, pedal=pedal)
        if progress:
            progress(1.0)
        log(f"✔ MIDI creado: {out}")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pending_pdfs(in_dir: Path, out_dir: Path, redo: bool = False) -> list[Path]:
    res = []
    for p in sorted(in_dir.glob("*.pdf")) + sorted(in_dir.glob("*.PDF")):
        mid = out_dir / f"{p.stem}.mid"
        if redo or not mid.exists() or mid.stat().st_mtime < p.stat().st_mtime:
            if p not in res:
                res.append(p)
    return res
