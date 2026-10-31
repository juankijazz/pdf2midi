import multiprocessing
import os
import sys


def _fix_streams():
    # Con --noconsole (Windows) sys.stdout/sys.stderr son None: homr escribe en stderr.
    if sys.stderr is None or sys.stdout is None:
        from . import config
        try:
            log = open(config.config_path().with_name("last_run.log"), "w", encoding="utf-8", errors="replace")
        except Exception:
            log = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log


def main(argv=None):
    multiprocessing.freeze_support()
    _fix_streams()
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print("Uso:\n  pdf2midi                      abre la ventana\n"
              "  pdf2midi ENTRADA.pdf [CARPETA_SALIDA] [--bpm N] [--pedal]   convierte sin ventana")
        return 0
    if argv:
        from .core import convert_pdf
        pdf = argv[0]
        rest = [a for a in argv[1:] if not a.startswith("--")]
        bpm = 90.0
        if "--bpm" in argv:
            bpm = float(argv[argv.index("--bpm") + 1])
            rest = [a for a in rest if a != argv[argv.index("--bpm") + 1]]
        out = rest[0] if rest else os.path.dirname(os.path.abspath(pdf))
        convert_pdf(pdf, out, bpm=bpm, pedal="--pedal" in argv, log=print)
        return 0
    from .gui import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
