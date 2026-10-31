# PDF2MIDI

Convierte partituras en PDF (escaneadas/imagen **o** vectoriales) a archivos MIDI.
Todo funciona **sin internet** y en un **único `PDF2MIDI.exe`**.

## Uso
1. Abre `PDF2MIDI.exe` (el primer arranque tarda unos segundos en descomprimirse).
2. Pulsa **Abrir carpeta** junto a «Meter los PDF aquí» y copia tus PDF.
3. Pulsa **Convertir todos los PDF de la carpeta**. Los `.mid` aparecen en la carpeta de salida
   (puede ser la misma: marca «Usar la misma carpeta»).

Por defecto las carpetas son `Documentos\PDF2MIDI\Entrada` y `Documentos\PDF2MIDI\Salida`;
se pueden cambiar con **Elegir…** y se recuerdan.
Opciones: tempo (BPM), pedal de sustain, guardar MusicXML, vigilar la carpeta (convierte solo los PDF nuevos).

También por línea de comandos:

    PDF2MIDI.exe partitura.pdf CARPETA_SALIDA --bpm 88 --pedal

## IA local opcional (pestaña «IA local (visión)»)
Conecta con un modelo de visión que tengas corriendo en tu equipo y que hable el protocolo OpenAI:
**LM Studio** (`http://localhost:1234/v1`), **Unsloth Studio** (`http://localhost:8888/v1`, con la clave de
Settings → API), Ollama, llama.cpp o vLLM. Elige servidor, pulsa «Buscar modelos», elige uno con visión
y «Probar conexión y visión».
Con la casilla activada, el modelo lee de cada página el **tempo (♩ = 88), matices (p, mf…), crescendo/diminuendo,
rit., a tempo y calderones**, y se aplican al MIDI. Las notas siguen saliendo del motor OMR integrado:
los modelos de visión locales no leen bien un pentagrama, pero sí el texto impreso.
Modelos recomendados: Qwen3-VL 8B (12-16 GB) o 32B (24 GB+), Gemma 3/4 con visión, MiniCPM-V 4.5.

## Calidad
El reconocimiento de partituras (OMR) es automático y **no es perfecto**: en páginas sencillas acierta casi todo, pero puede fallar con alteraciones, voces superpuestas, tresillos o
cambios de armadura. Por eso, junto al `.mid` se guarda un `.musicxml` por página: ábrelo en
MuseScore (gratis) para corregir y volver a exportar el MIDI.
La duración de cada compás se ajusta automáticamente para que las dos manos no se desincronicen.
El tempo no se lee de la partitura: se usa el valor de la ventana.

## Construir el .exe (Windows 10/11, 64 bits)
**Opción A – en tu PC:** instala Python 3.12 (64 bits, marcando «Add to PATH») y ejecuta `build_windows.bat`.
Tarda unos minutos y deja `dist\PDF2MIDI.exe` (≈ 270 MB, con los modelos incluidos).

**Opción B – GitHub Actions:** sube esta carpeta a un repositorio de GitHub y lanza el flujo
«Build PDF2MIDI.exe» (pestaña Actions → Run workflow). Descarga el `.exe` de los *artifacts*.

## Componentes open source
- [homr](https://github.com/liebharc/homr) – reconocimiento óptico de partituras (AGPL-3.0)
- ONNX Runtime, OpenCV, Shapely, musicxml – inferencia y procesado de imagen
- [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) – renderizado de PDF (PDFium, Apache-2.0/BSD)
- mido – escritura de MIDI · PyInstaller – empaquetado · Tkinter – interfaz

> Licencia: homr es AGPL-3.0, por lo que si redistribuyes el `.exe` debes ofrecer también el código fuente
> (este proyecto completo) bajo la misma licencia.

## Estructura
    src/pdf2midi/core.py          PDF → páginas → homr → MusicXML → MIDI
    src/pdf2midi/musicxml2midi.py conversor MusicXML→MIDI (reparación rítmica, ligaduras, dinámicas)
    src/pdf2midi/gui.py           ventana (carpetas de entrada/salida, progreso, vigilancia)
    pdf2midi.spec                 receta de PyInstaller (un solo .exe)
    build_windows.bat             construcción local · .github/workflows/build.yml  construcción en la nube
