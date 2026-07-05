import json
import os
from functools import lru_cache

from app.attack.stix_source import ensure_enterprise_attack_stix
from app.attack.techniques import Technique, load_techniques
from app.core.config import settings


def load_tactics(stix_path: str) -> list[tuple[str, str]]:
    """Return (shortname, display name) tactics in official matrix column order.

    Derived from the bundle's x-mitre-matrix.tactic_refs rather than hardcoded:
    the tactic set isn't as stable as it looks (this bundle already splits the
    former "Defense Evasion" into "Defense Impairment" and "Stealth").
    """
    with open(stix_path) as f:
        bundle = json.load(f)

    tactics_by_id = {
        obj["id"]: (obj["x_mitre_shortname"], obj["name"])
        for obj in bundle["objects"]
        if obj["type"] == "x-mitre-tactic"
    }
    matrix = next(obj for obj in bundle["objects"] if obj["type"] == "x-mitre-matrix")
    return [tactics_by_id[ref] for ref in matrix["tactic_refs"] if ref in tactics_by_id]


def _technique_summary(tech: Technique) -> dict:
    return {"id": tech.attack_id, "name": tech.name, "url": tech.url}


def build_catalog(techniques: list[Technique], tactics_order: list[tuple[str, str]]) -> dict:
    """Group the flat technique list into the tactic x technique x sub-technique
    tree a Navigator-style matrix renders. A technique can appear under multiple
    tactic columns, matching real ATT&CK Navigator behavior.
    """
    children_by_parent: dict[str, list[Technique]] = {}
    for tech in techniques:
        if tech.is_subtechnique:
            parent_id = tech.attack_id.split(".")[0]
            children_by_parent.setdefault(parent_id, []).append(tech)

    tactics = []
    for tactic_id, tactic_name in tactics_order:
        tactic_techniques = []
        for tech in techniques:
            if tech.is_subtechnique or tactic_id not in tech.tactics:
                continue
            subtechniques = [
                _technique_summary(sub)
                for sub in children_by_parent.get(tech.attack_id, [])
                if tactic_id in sub.tactics
            ]
            tactic_techniques.append({**_technique_summary(tech), "subtechniques": subtechniques})
        tactics.append({"id": tactic_id, "name": tactic_name, "techniques": tactic_techniques})

    return {"tactics": tactics}


@lru_cache(maxsize=1)
def get_catalog() -> dict:
    stix_path = ensure_enterprise_attack_stix(
        os.path.join(settings.attack_stix_dir, "enterprise-attack.json")
    )
    return build_catalog(load_techniques(stix_path), load_tactics(stix_path))
