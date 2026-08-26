"""Cross-encoder reranker over the fused retrieval pool (pipeline stage 4's
final refinement).

Why a reranker and not more candidates: five separate candidate-*budget*
mechanisms were measured and all failed at menu width 8 (CLAUDE.md, cycles
6-9), while the raw half-pools already contain 97% of the labelled core
techniques. The loss is fusion's *selection*, so this re-scores candidates
retrieval already found rather than adding any.

Local-first: a small ONNX cross-encoder runs in-process on CPU via
`onnxruntime` + `tokenizers`, both of which chromadb already pulls in — no new
Python dependency and no network at runtime. If the model files are absent the
module degrades to a no-op and fusion behaves exactly as before, so a checkout
without them still works.

Two measured design points, neither obvious (2026-08-24, cycle 12):

* **Score sentence windows, not the whole chunk.** The same model over whole
  chunk bodies is a *disaster* — pure-reranker coverage 41 vs fusion's 60 on
  the three labelled reports — while over sentence windows it is the best
  selector measured (62-63). A ~1200-char security narrative is nothing like
  the short queries an MS MARCO cross-encoder was trained on, and a chunk-level
  score also re-averages away exactly the minority sentences the window half
  exists to rescue. Each candidate keeps its best window score.
* **Blend with RRF rather than replacing it.** Pure reranker top-8 wins
  openslop (+5) but costs grove 3 — the cross-encoder is domain-mismatched
  often enough that fusion's agreement signal is still worth half the vote.
  A 50/50 blend of min-max-normalized CE score and normalized RRF score
  improved 2 of 3 reports and regressed none.
"""

import os
import threading

import numpy as np

from app.core.config import settings

# Candidates reranked per chunk, taken best-first by fused RRF score. Measured
# (cycle 12): 24 matches the full-pool result exactly (coverage 63, 2 reports
# up / 0 down) at a quarter of the cost, while 16 starts losing techniques.
RERANK_DEPTH = 24
# Weight of the cross-encoder against fused RRF in the final ordering.
RERANK_BLEND = 0.5
_MAX_TOKENS = 512
_BATCH = 64

_lock = threading.Lock()
_state: dict | None = None


def _load() -> dict | None:
    """Lazily build the ONNX session + tokenizer once per process. Returns None
    (permanently, cached) when the model isn't present."""
    global _state
    if _state is not None:
        return _state if _state["session"] else None
    with _lock:
        if _state is not None:
            return _state if _state["session"] else None
        model = os.path.join(settings.rerank_model_dir, settings.rerank_model_file)
        tokenizer = os.path.join(settings.rerank_model_dir, "tokenizer.json")
        if not (os.path.exists(model) and os.path.exists(tokenizer)):
            _state = {"session": None}
            return None
        import onnxruntime as ort
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(tokenizer)
        tok.enable_truncation(max_length=_MAX_TOKENS)
        tok.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, settings.rerank_threads)
        session = ort.InferenceSession(model, options, providers=["CPUExecutionProvider"])
        _state = {
            "session": session,
            "tokenizer": tok,
            "type_ids": any(i.name == "token_type_ids" for i in session.get_inputs()),
        }
        return _state


def available() -> bool:
    return settings.rerank and _load() is not None


def _score(pairs: list[tuple[str, str]]) -> np.ndarray:
    state = _load()
    tok, session = state["tokenizer"], state["session"]
    out = np.empty(len(pairs), dtype=np.float32)
    for i in range(0, len(pairs), _BATCH):
        enc = tok.encode_batch(pairs[i : i + _BATCH])
        feed = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
        }
        if state["type_ids"]:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        out[i : i + _BATCH] = session.run(None, feed)[0].reshape(-1)
    return out


def rerank_scores(windows: list[str], documents: dict[str, str]) -> dict[str, float]:
    """Best cross-encoder score per candidate across the chunk's sentence
    windows. `documents` maps attack_id -> its KB document (name + description).
    Returns {} when the model is unavailable, which callers treat as "no
    opinion" and fall back to plain fused ordering."""
    if not windows or not documents or not available():
        return {}
    ids = list(documents)
    scores = _score([(w, documents[a]) for w in windows for a in ids])
    best: dict[str, float] = {}
    for w_index in range(len(windows)):
        window_scores = scores[w_index * len(ids) : (w_index + 1) * len(ids)]
        for attack_id, score in zip(ids, window_scores):
            value = float(score)
            if attack_id not in best or value > best[attack_id]:
                best[attack_id] = value
    return best


def blended_order(fused: dict[str, float], ce: dict[str, float]) -> list[str]:
    """Candidate ids best-first under the 50/50 blend of min-max-normalized
    cross-encoder score and normalized RRF score. Candidates outside
    RERANK_DEPTH carry no CE score and are floored to 0 on that half, so they
    rank on fusion alone rather than being dropped."""
    if not ce:
        return sorted(fused, key=lambda a: (-fused[a], a))
    lo, hi = min(ce.values()), max(ce.values())
    span = (hi - lo) or 1.0
    top = max(fused.values()) or 1.0
    blend = {
        a: (1 - RERANK_BLEND) * ((ce.get(a, lo) - lo) / span)
        + RERANK_BLEND * (fused[a] / top)
        for a in fused
    }
    return sorted(blend, key=lambda a: (-blend[a], a))
