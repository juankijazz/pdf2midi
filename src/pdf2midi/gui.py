import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, config
from .core import Cancelled, convert_pdf, pending_pdfs


def open_folder(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"PDF → MIDI  (partituras de piano)  v{__version__}")
        self.geometry("760x560")
        self.minsize(680, 480)
        self.cfg = config.load()
        self.q: "queue.Queue" = queue.Queue()
        self.worker = None
        self.cancel_flag = False
        self.watching = False
        self.failed = set()
        self._build()
        self.after(100, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------ UI
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)

        self.v_in = tk.StringVar(value=self.cfg["entrada"])
        self.v_out = tk.StringVar(value=self.cfg["salida"])
        self.v_same = tk.BooleanVar(value=self.cfg["misma"])
        self.v_bpm = tk.IntVar(value=self.cfg["bpm"])
        self.v_pedal = tk.BooleanVar(value=self.cfg["pedal"])
        self.v_xml = tk.BooleanVar(value=self.cfg["musicxml"])
        self.v_redo = tk.BooleanVar(value=self.cfg["rehacer"])
        self.v_watch = tk.BooleanVar(value=False)

        box = ttk.LabelFrame(f, text="Carpetas")
        box.pack(fill="x", **pad)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Meter los PDF aquí:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(box, textvariable=self.v_in).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(box, text="Elegir…", command=lambda: self._choose(self.v_in)).grid(row=0, column=2, **pad)
        ttk.Button(box, text="Abrir carpeta", command=lambda: open_folder(self.v_in.get())).grid(row=0, column=3, **pad)
        ttk.Label(box, text="Se guardan los MIDI aquí:").grid(row=1, column=0, sticky="w", **pad)
        self.e_out = ttk.Entry(box, textvariable=self.v_out)
        self.e_out.grid(row=1, column=1, sticky="ew", **pad)
        self.b_out = ttk.Button(box, text="Elegir…", command=lambda: self._choose(self.v_out))
        self.b_out.grid(row=1, column=2, **pad)
        ttk.Button(box, text="Abrir carpeta", command=lambda: open_folder(self._out_dir())).grid(row=1, column=3, **pad)
        ttk.Checkbutton(box, text="Usar la misma carpeta para entrada y salida",
                        variable=self.v_same, command=self._same_changed).grid(row=2, column=0, columnspan=4, sticky="w", **pad)

        opt = ttk.LabelFrame(f, text="Opciones")
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="Tempo (negras/min):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(opt, from_=30, to=240, width=6, textvariable=self.v_bpm).grid(row=0, column=1, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Añadir pedal de sustain (uno por compás)", variable=self.v_pedal).grid(row=0, column=2, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Guardar también MusicXML (para corregir en MuseScore)", variable=self.v_xml).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Volver a convertir los que ya tienen MIDI", variable=self.v_redo).grid(row=1, column=2, sticky="w", **pad)

        bar = ttk.Frame(f)
        bar.pack(fill="x", **pad)
        self.b_go = ttk.Button(bar, text="Convertir todos los PDF de la carpeta", command=self.start)
        self.b_go.pack(side="left")
        self.b_cancel = ttk.Button(bar, text="Cancelar", command=self.cancel, state="disabled")
        self.b_cancel.pack(side="left", padx=8)
        ttk.Checkbutton(bar, text="Vigilar la carpeta y convertir los PDF nuevos",
                        variable=self.v_watch, command=self._watch_changed).pack(side="left", padx=12)

        self.pb = ttk.Progressbar(f, maximum=100)
        self.pb.pack(fill="x", **pad)
        self.log = tk.Text(f, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)
        self._same_changed()
        self._log("Listo. Copia tus PDF a la carpeta de entrada y pulsa «Convertir».")
        self._log("Funciona con PDF escaneados (imagen) y con PDF vectoriales. Todo se procesa en tu equipo, sin internet.")

    # ------------------------------------------------------------ helpers
    def _choose(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)
            self._same_changed()

    def _same_changed(self):
        same = self.v_same.get()
        self.e_out.configure(state="disabled" if same else "normal")
        self.b_out.configure(state="disabled" if same else "normal")

    def _out_dir(self) -> str:
        return self.v_in.get() if self.v_same.get() else self.v_out.get()

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _save_cfg(self):
        config.save({"entrada": self.v_in.get(), "salida": self.v_out.get(), "misma": self.v_same.get(),
                     "bpm": self.v_bpm.get(), "pedal": self.v_pedal.get(), "musicxml": self.v_xml.get(),
                     "rehacer": self.v_redo.get()})

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self._log(val)
                elif kind == "pb":
                    self.pb["value"] = val
                elif kind == "done":
                    self.b_go.configure(state="normal")
                    self.b_cancel.configure(state="disabled")
                    self.worker = None
        except queue.Empty:
            pass
        if self.watching and self.worker is None:
            self._watch_tick()
        self.after(150, self._pump)

    # ------------------------------------------------------------ acciones
    def start(self, auto=False):
        if self.worker is not None:
            return
        in_dir, out_dir = Path(self.v_in.get()), Path(self._out_dir())
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = pending_pdfs(in_dir, out_dir, self.v_redo.get() and not auto)
        if auto:
            files = [f for f in files if f not in self.failed]
        if not files:
            if not auto:
                self._log("No hay PDF pendientes en la carpeta de entrada.")
            return
        self._save_cfg()
        self.cancel_flag = False
        self.b_go.configure(state="disabled")
        self.b_cancel.configure(state="normal")
        opts = dict(bpm=float(self.v_bpm.get()), pedal=self.v_pedal.get(), keep_musicxml=self.v_xml.get())
        self.worker = threading.Thread(target=self._run, args=(files, out_dir, opts), daemon=True)
        self.worker.start()

    def _run(self, files, out_dir, opts):
        put = self.q.put
        for i, f in enumerate(files):
            if self.cancel_flag:
                break
            try:
                convert_pdf(f, out_dir, log=lambda m: put(("log", m)),
                            progress=lambda p, i=i: put(("pb", 100 * (i + p) / len(files))),
                            cancel=lambda: self.cancel_flag, **opts)
            except Cancelled:
                put(("log", "Cancelado."))
                break
            except Exception as e:
                self.failed.add(f)
                put(("log", f"✖ Error con {f.name}: {e}"))
        put(("pb", 100))
        put(("done", None))

    def cancel(self):
        self.cancel_flag = True
        self._log("Cancelando al terminar la página actual…")

    def _watch_changed(self):
        self.watching = self.v_watch.get()
        self._log("Vigilando la carpeta de entrada…" if self.watching else "Vigilancia desactivada.")
        self._last_watch = 0.0

    def _watch_tick(self):
        import time
        now = time.time()
        if now - getattr(self, "_last_watch", 0) > 4:
            self._last_watch = now
            self.start(auto=True)

    def _close(self):
        self._save_cfg()
        self.cancel_flag = True
        self.destroy()
        os._exit(0)  # no esperar a hilos de onnxruntime


def run():
    App().mainloop()
