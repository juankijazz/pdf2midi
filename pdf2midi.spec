# -*- mode: python ; coding: utf-8 -*-
# Genera UN solo ejecutable (onefile) con todo incluido: motor OMR (homr),
# modelos ONNX, renderizador de PDF (pdfium) y conversor MIDI.
import importlib.util
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("homr", "musicxml", "pypdfium2", "pypdfium2_raw", "onnxruntime",
            "shapely", "pyclipper", "mido"):
    if importlib.util.find_spec(pkg) is None:
        continue
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run_pdf2midi.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"],
    excludes=["rapidocr", "matplotlib", "torch", "tensorflow", "IPython", "pytest", "notebook", "scipy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PDF2MIDI",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # ventana sin consola en Windows
    icon=None,
)
