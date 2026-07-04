import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import chromadb
import httpx

from app.attack.embeddings import embed_text
from app.attack.stix_source import ensure_enterprise_attack_stix
from app.attack.techniques import Technique, load_techniques
from app.core.config import settings

# Bundled, pre-embedded copy of the KB (committed to git) so a fresh checkout
# can be indexed instantly without a local Ollama model or network access.
# Regenerate it with `--refresh` after a MITRE ATT&CK release update.
PREBUILT_KB_PATH = os.path.join(os.path.dirname(__file__), "prebuilt_kb", "attack_techniques.json")
EMBED_WORKERS = 4  # matches the ollama service's OLLAMA_NUM_PARALLEL in docker-compose.yml
EMBED_TIMEOUT = 120.0
EMBED_RETRIES = 3
EMBED_BATCH_SIZE = 25  # techniques upserted into Chroma per batch, so a crash keeps prior progress


def _load_prebuilt_kb(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _technique_text(tech: Technique) -> str:
    return f"{tech.name}\n\n{tech.description}"


def _technique_metadata(tech: Technique) -> dict:
    return {
        "attack_id": tech.attack_id,
        "name": tech.name,
        "tactics": ",".join(tech.tactics),
        "url": tech.url,
        "is_subtechnique": tech.is_subtechnique,
    }


def _embed_with_retry(client: httpx.Client, text: str) -> list[float]:
    last_exc: Exception | None = None
    for attempt in range(1, EMBED_RETRIES + 1):
        try:
            return embed_text(text, client)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < EMBED_RETRIES:
                time.sleep(2 * attempt)
    raise last_exc


def _embed_and_index(techniques: list[Technique], collection) -> None:
    """Embed techniques concurrently and upsert them into Chroma in small batches,
    so an interrupted run keeps whatever already completed instead of losing it all.
    On failure, cancels not-yet-started work instead of draining the whole queue.
    """
    total = len(techniques)
    batch: list[Technique] = []
    batch_embeddings: list[list[float]] = []

    def flush():
        if not batch:
            return
        collection.upsert(
            ids=[t.attack_id for t in batch],
            embeddings=list(batch_embeddings),
            documents=[_technique_text(t) for t in batch],
            metadatas=[_technique_metadata(t) for t in batch],
        )
        batch.clear()
        batch_embeddings.clear()

    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        pool = ThreadPoolExecutor(max_workers=EMBED_WORKERS)
        try:
            future_to_tech = {
                pool.submit(_embed_with_retry, client, _technique_text(t)): t for t in techniques
            }
            for done, future in enumerate(as_completed(future_to_tech), start=1):
                tech = future_to_tech[future]
                embedding = future.result()
                batch.append(tech)
                batch_embeddings.append(embedding)
                print(f"  embedded {done}/{total}: {tech.attack_id} {tech.name}")
                if len(batch) >= EMBED_BATCH_SIZE:
                    flush()
        except BaseException:
            flush()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            flush()
            pool.shutdown(wait=True)


def _export_collection_to_seed(collection, path: str) -> None:
    data = collection.get(include=["embeddings", "documents", "metadatas"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "ids": data["ids"],
                "documents": data["documents"],
                "embeddings": [[float(x) for x in row] for row in data["embeddings"]],
                "metadatas": data["metadatas"],
            },
            f,
        )


def build_kb(refresh: bool = False) -> None:
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    collection = client.get_or_create_collection(settings.attack_collection)

    if not refresh and collection.count() > 0:
        print(
            f"Collection '{settings.attack_collection}' already has {collection.count()} "
            "techniques indexed, skipping."
        )
        return

    seed = None if refresh else _load_prebuilt_kb(PREBUILT_KB_PATH)
    if seed is not None:
        print(
            f"Restoring {len(seed['ids'])} techniques from bundled seed {PREBUILT_KB_PATH} "
            "(no embedding model or network access needed)"
        )
        collection.upsert(
            ids=seed["ids"],
            embeddings=seed["embeddings"],
            documents=seed["documents"],
            metadatas=seed["metadatas"],
        )
        print(f"Indexed {collection.count()} techniques into Chroma collection '{settings.attack_collection}'")
        return

    stix_path = ensure_enterprise_attack_stix(
        os.path.join(settings.attack_stix_dir, "enterprise-attack.json")
    )
    techniques = load_techniques(stix_path)
    print(f"Loaded {len(techniques)} active techniques from {stix_path}")

    already_indexed = set(collection.get(include=[])["ids"])
    pending = [t for t in techniques if t.attack_id not in already_indexed]
    if already_indexed:
        print(
            f"{len(already_indexed)} techniques already indexed from a previous run, "
            f"resuming with {len(pending)} remaining"
        )

    if pending:
        _embed_and_index(pending, collection)

    print(f"Indexed {collection.count()} techniques into Chroma collection '{settings.attack_collection}'")

    _export_collection_to_seed(collection, PREBUILT_KB_PATH)
    print(f"Wrote refreshed seed to {PREBUILT_KB_PATH} — commit this file to ship the updated KB.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Re-embed from the current ATT&CK release via Ollama instead of restoring the "
            "bundled seed, and rewrite the seed file with the result (e.g. after a MITRE "
            "ATT&CK release update). Safe to re-run after an interruption — already-embedded "
            "techniques are skipped."
        ),
    )
    args = parser.parse_args()
    build_kb(refresh=args.refresh)
