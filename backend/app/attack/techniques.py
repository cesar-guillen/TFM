import json
from dataclasses import dataclass


@dataclass
class Technique:
    attack_id: str
    name: str
    description: str
    tactics: list[str]
    url: str
    is_subtechnique: bool


def _mitre_attack_ref(obj: dict) -> dict | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref
    return None


def load_techniques(stix_path: str) -> list[Technique]:
    """Extract active (non-revoked, non-deprecated) techniques from a raw
    MITRE ATT&CK STIX 2.1 bundle. Ignores relationships, malware/tool,
    mitigation, campaign, and other object types the matrix doesn't need.
    """
    with open(stix_path) as f:
        bundle = json.load(f)

    techniques = []
    for obj in bundle["objects"]:
        if obj["type"] != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue

        ref = _mitre_attack_ref(obj)
        if ref is None:
            continue

        tactics = [
            phase["phase_name"]
            for phase in obj.get("kill_chain_phases", [])
            if phase.get("kill_chain_name") == "mitre-attack"
        ]

        techniques.append(
            Technique(
                attack_id=ref["external_id"],
                name=obj["name"],
                description=obj.get("description", ""),
                tactics=tactics,
                url=ref.get("url", ""),
                is_subtechnique=obj.get("x_mitre_is_subtechnique", False),
            )
        )

    return techniques
