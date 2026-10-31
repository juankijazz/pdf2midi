"""Descarga los modelos ONNX de homr para que PyInstaller los incluya en el .exe."""
import sys
import types

# homr importa rapidocr (solo para leer títulos); aquí no hace falta instalarlo/usarlo.
if "rapidocr" not in sys.modules:
    try:
        import rapidocr  # noqa: F401
    except Exception:
        m = types.ModuleType("rapidocr")
        m.RapidOCR = object
        sys.modules["rapidocr"] = m

from homr.main import download_weights  # noqa: E402

download_weights(False, False, False)
print("Modelos listos.")
