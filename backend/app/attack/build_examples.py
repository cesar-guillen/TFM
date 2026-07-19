"""Build the ATT&CK procedure-examples collection (see EXAMPLE_RETRIEVAL).

MITRE's STIX bundle carries thousands of "uses" relationships whose
descriptions are procedure examples written exactly like incident-report prose
("Babuk can stop specific services related to backups") — the vocabulary
report chunks actually use, which technique descriptions often lack (the
measured cause of several systematically-unretrievable techniques, e.g. T1489
Service Stop against "backup-related and database services were forcibly
stopped").

Each example is embedded as its OWN vector carrying its technique's full
metadata. Do not concatenate examples into the technique documents instead:
that variant was measured to dilute the technique embeddings toward a generic
"threat actor did things" centroid and regressed coverage (Meridian Health
core reachable 18/24 → 14/24).

    docker compose exec backend python -m app.attack.build_examples

Requires the STIX bundle (downloaded/cached like build_kb --refresh) and the
Ollama embed model. Safe to re-run: the collection is rebuilt from scratch.
"""

import json
import re
from collections import defaultdict

import httpx

from app.attack.embeddings import embed_texts
from app.attack.stix_source import ensure_enterprise_attack_stix
from app.core.chroma import (
    COSINE_SPACE,
    get_attack_collection,
    get_chroma_client,
)
from app.core.config import settings
import os

# Per technique: shortest examples first (terse ones carry the canonical
# phrasing — "X used scheduled tasks to maintain persistence" — while long
# ones are actor-specific stories), capped so hub techniques with hundreds of
# examples (T1105 has 515) don't dominate the collection.
MAX_EXAMPLES_PER_TECHNIQUE = 12
MIN_EXAMPLE_CHARS = 25

EMBED_BATCH = 25
_LINK_RE = re.compile(r"\[([^\]]*)\]\(https?://[^)]*\)")
_CITATION_RE = re.compile(r"\(Citation:[^)]*\)")


def load_examples(stix_path: str) -> dict[str, list[str]]:
    """attack_id -> cleaned procedure-example texts (capped, shortest first)."""
    with open(stix_path) as f:
        objects = json.load(f)["objects"]

    stix_to_attack_id: dict[str, str] = {}
    for obj in objects:
        if (
            obj.get("type") == "attack-pattern"
            and not obj.get("revoked")
            and not obj.get("x_mitre_deprecated")
        ):
            for ref in obj.get("external_references", []):
                if ref.get("source_name") == "mitre-attack":
                    stix_to_attack_id[obj["id"]] = ref["external_id"]

    raw: dict[str, set[str]] = defaultdict(set)
    for obj in objects:
        if obj.get("type") != "relationship" or obj.get("relationship_type") != "uses":
            continue
        attack_id = stix_to_attack_id.get(obj.get("target_ref"))
        description = obj.get("description")
        if not attack_id or not description:
            continue
        cleaned = _CITATION_RE.sub("", _LINK_RE.sub(r"\1", description)).strip()
        if len(cleaned) >= MIN_EXAMPLE_CHARS:
            raw[attack_id].add(cleaned)

    return {
        attack_id: sorted(texts, key=len)[:MAX_EXAMPLES_PER_TECHNIQUE]
        for attack_id, texts in raw.items()
    }


def build_examples() -> None:
    stix_path = ensure_enterprise_attack_stix(
        os.path.join(settings.attack_stix_dir, "enterprise-attack.json")
    )
    examples = load_examples(stix_path)

    # Only techniques present in the KB (active, non-deprecated), carrying the
    # KB's own metadata so example hits are directly usable as TechniqueMatch.
    kb = get_attack_collection().get(include=["metadatas"])
    metadata_by_id = dict(zip(kb["ids"], kb["metadatas"]))

    ids, documents, metadatas = [], [], []
    for attack_id, texts in sorted(examples.items()):
        meta = metadata_by_id.get(attack_id)
        if meta is None:
            continue  # example for a technique the KB dropped
        for i, text in enumerate(texts):
            ids.append(f"{attack_id}:ex{i}")
            documents.append(text)
            metadatas.append(meta)

    client = get_chroma_client()
    try:
        client.delete_collection(settings.attack_examples_collection)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        settings.attack_examples_collection, metadata=COSINE_SPACE
    )

    print(f"Embedding {len(ids)} procedure examples "
          f"({len({m['attack_id'] for m in metadatas})} techniques)…")
    with httpx.Client(timeout=300) as http_client:
        for start in range(0, len(ids), EMBED_BATCH):
            end = start + EMBED_BATCH
            embeddings = embed_texts(documents[start:end], http_client)
            collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings,
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            if start % (EMBED_BATCH * 20) == 0:
                print(f"  {min(end, len(ids))}/{len(ids)}")
    print(f"Indexed {collection.count()} examples into "
          f"'{settings.attack_examples_collection}'")


if __name__ == "__main__":
    build_examples()
