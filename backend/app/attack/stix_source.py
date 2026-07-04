import os

import httpx

ENTERPRISE_ATTACK_URL = (
    "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
)


def ensure_enterprise_attack_stix(dest_path: str) -> str:
    if os.path.exists(dest_path):
        return dest_path

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with httpx.stream("GET", ENTERPRISE_ATTACK_URL, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    return dest_path
