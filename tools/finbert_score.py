"""Tono financiero de los titulares con FinBERT (ProsusAI/finbert), como proceso efímero de la nota horaria.

Tiene su propio entorno (torch de CPU + transformers) porque transformers exige una versión de huggingface_hub
distinta de la que usa TimesFM; mezclarlos rompería TimesFM:
  %LOCALAPPDATA%\\ai-trading-lab\\finbert\\venv\\Scripts\\python.exe -m tools.finbert_score --descargar   (una vez)
  ... -m tools.finbert_score < contexto.json      (lo lanza el orquestador cada hora)
Lee por la entrada estándar {"titulares": [{"titulo": ..., "simbolos": [...]}]} e imprime un JSON en la última
línea. La corrida horaria nunca descarga nada: trabaja sin conexión sobre el modelo ya bajado. Al terminar, el
proceso muere y el sistema recupera toda su memoria (≈ 0,8 GB en el pico).
Es contexto, no señal: igual que VADER, no propone, aprueba ni rechaza operaciones.
"""
import json
import os
import sys
from pathlib import Path

REPO = "ProsusAI/finbert"
REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"  # revisión fijada: lo que se ejecuta no cambia por sorpresa
FILES = ("config.json", "pytorch_model.bin", "vocab.txt", "tokenizer_config.json", "special_tokens_map.json")
HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ai-trading-lab" / "finbert"
MODEL_DIR = HOME / "modelo"
PYTHON = HOME / "venv" / "Scripts" / "python.exe"
MAX_TITLES = 200
BATCH = 16


def _mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def aggregate(items, probs, labels):
    """items: [{titulo, simbolos}]; probs: [[probabilidad por etiqueta]]; labels: nombre de cada columna.
    Tono de un titular = p(positive) - p(negative), de -1 a 1."""
    pos, neg = labels.index("positive"), labels.index("negative")
    scores = [p[pos] - p[neg] for p in probs]
    by_symbol = {}
    for item, s in zip(items, scores):
        for sym in item.get("simbolos") or []:
            by_symbol.setdefault(sym, []).append(s)
    ranked = sorted(zip(scores, (item["titulo"] for item in items)), key=lambda x: x[0])
    return {"modelo": REPO, "n": len(scores), "mercado": _mean(scores),
            "positivos": sum(s > 0.3 for s in scores), "negativos": sum(s < -0.3 for s in scores),
            "por_activo": {k: {"tono": _mean(v), "n": len(v)} for k, v in sorted(by_symbol.items())},
            "mas_negativo": [{"tono": round(s, 3), "titulo": t[:160]} for s, t in ranked[:2] if s < -0.3],
            "mas_positivo": [{"tono": round(s, 3), "titulo": t[:160]} for s, t in ranked[::-1][:2] if s > 0.3]}


def download():
    from huggingface_hub import hf_hub_download
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        hf_hub_download(REPO, name, revision=REVISION, local_dir=MODEL_DIR)
    # Los pesos vienen en formato pickle: se leen una sola vez en modo seguro y se guardan como safetensors,
    # que se carga sin ejecutar código. Después se borra el .bin.
    import torch
    from safetensors.torch import save_file
    state = torch.load(MODEL_DIR / "pytorch_model.bin", map_location="cpu", weights_only=True)
    save_file({k: v.contiguous() for k, v in state.items()}, str(MODEL_DIR / "model.safetensors"))
    (MODEL_DIR / "pytorch_model.bin").unlink()
    return {"descargado": str(MODEL_DIR), "revision": REVISION}


def score(items):
    if not items:
        return {"modelo": REPO, "n": 0, "mercado": None, "por_activo": {}}
    os.environ["HF_HUB_OFFLINE"] = "1"  # nunca descargar en la corrida horaria
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR, use_safetensors=True).eval()
    labels = [model.config.id2label[i].lower() for i in range(model.config.num_labels)]
    probs = []
    with torch.inference_mode():
        for i in range(0, len(items), BATCH):
            batch = tokenizer([x["titulo"] for x in items[i:i + BATCH]], padding=True, truncation=True, max_length=64, return_tensors="pt")
            probs += torch.softmax(model(**batch).logits, dim=-1).tolist()
    return aggregate(items, probs, labels)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding="utf-8")
    if "--descargar" in argv:
        print(json.dumps(download()))
        return 0
    context = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    items = [{"titulo": str(t.get("titulo") or "")[:300], "simbolos": list(t.get("simbolos") or [])}
             for t in (context.get("titulares") or [])[:MAX_TITLES] if t.get("titulo")]
    print(json.dumps(score(items), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
