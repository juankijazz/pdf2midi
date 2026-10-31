"""Cliente mínimo (solo biblioteca estándar) para servidores locales compatibles con OpenAI:
LM Studio (http://localhost:1234/v1), Unsloth Studio (http://localhost:8888/v1),
Ollama (:11434/v1), llama.cpp (:8080/v1), vLLM (:8000/v1)…"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request

PRESETS = {
    "LM Studio": "http://localhost:1234/v1",
    "Unsloth Studio": "http://localhost:8888/v1",
    "Ollama": "http://localhost:11434/v1",
    "llama.cpp (llama-server)": "http://localhost:8080/v1",
    "vLLM": "http://localhost:8000/v1",
    "Otro (OpenAI-compatible)": "http://localhost:1234/v1",
}

VISION_HINTS = ("vl", "vision", "llava", "gemma", "minicpm", "pixtral", "qwen", "internvl",
                "mistral-small", "llama-3.2", "phi-3.5-v", "phi-4-multimodal", "molmo", "smol")


class LLMError(Exception):
    pass


def normalize_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        raise LLMError("Falta la dirección del servidor.")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    if not re.search(r"/v1$", url):
        url += "/v1"
    return url


def image_to_data_url(image, max_side: int = 1800, quality: int = 88) -> str:
    """image: PIL.Image o ruta. Devuelve data:image/jpeg;base64,…"""
    from PIL import Image
    im = Image.open(image) if isinstance(image, str) else image
    im = im.convert("RGB")
    w, h = im.size
    s = max_side / max(w, h)
    if s < 1:
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def extract_json(text: str):
    """Saca el primer objeto JSON de la respuesta (quita <think>, ```json, texto alrededor)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise LLMError("La respuesta del modelo no contiene JSON.")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise LLMError("JSON incompleto en la respuesta del modelo.")


class VisionClient:
    def __init__(self, base_url: str, model: str = "", api_key: str = "", timeout: float = 600.0):
        self.base = normalize_base(base_url)
        self.model = model
        self.api_key = api_key.strip() if api_key else ""
        self.timeout = timeout

    # ---- HTTP
    def _request(self, path: str, payload=None, timeout=None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403):
                raise LLMError("El servidor rechazó la clave de API (revisa la clave).")
            raise LLMError(f"Error {e.code} del servidor: {body}")
        except urllib.error.URLError as e:
            raise LLMError(f"No se pudo conectar con {self.base}: {e.reason}. "
                           "¿Está el servidor local en marcha y el modelo cargado?")
        except TimeoutError:
            raise LLMError("El servidor tardó demasiado en responder.")

    # ---- API
    def list_models(self) -> list[str]:
        d = self._request("/models", timeout=10)
        ids = [m.get("id", "") for m in d.get("data", []) if m.get("id")]
        # primero los que parecen tener visión
        ids.sort(key=lambda i: (not any(h in i.lower() for h in VISION_HINTS), i.lower()))
        return ids

    def chat(self, system: str, user_text: str, image=None, max_tokens: int = 1500) -> str:
        if not self.model:
            raise LLMError("No hay modelo seleccionado.")
        content = [{"type": "text", "text": user_text}]
        if image is not None:
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image)}})
        payload = {"model": self.model, "temperature": 0, "max_tokens": max_tokens, "stream": False,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        d = self._request("/chat/completions", payload)
        try:
            return d["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("Respuesta inesperada del servidor.")

    def chat_json(self, system: str, user_text: str, image=None, max_tokens: int = 1500):
        return extract_json(self.chat(system, user_text, image, max_tokens))

    def test_vision(self) -> str:
        """Comprueba que el modelo acepta imágenes: le muestra un número y se lo pide."""
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGB", (320, 160), "white")
        d = ImageDraw.Draw(im)
        d.rectangle([10, 10, 310, 150], outline="black", width=4)
        d.text((95, 35), "47", fill="black", font=ImageFont.load_default(size=90))
        out = self.chat("Responde de forma muy breve.", "¿Qué número aparece en la imagen? Responde solo el número.", im, 40)
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        if "47" in out:
            return "✔ Conexión correcta y el modelo ve imágenes."
        return f"Conecta, pero el modelo no leyó la imagen bien (respondió: «{out[:60]}»). ¿Es un modelo con visión?"
