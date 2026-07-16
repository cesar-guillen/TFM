"""Hand-labelled ATT&CK ground truth for the eval-harness reference reports.

Labelled by a human reading each narrative (sections referenced as §N). These
are judgment calls and deliberately editable — the harness reads the registry,
it does not hardcode any set, so revise as understanding improves. ATT&CK
labelling is genuinely subjective at the margins: an "unexpected" mapping is a
*candidate* false positive for a human to review, and reviewed-and-defensible
ones should be promoted into ACCEPTABLE rather than left penalized. Keep the
evidence note on each entry: it is why the label is defensible and where to
look in the report.

Per report:
- `core`      — unambiguous adversary activity a good mapping MUST recover.
                Recall is scored against this set.
- `acceptable`— reasonable if mapped but not required: parents of core
                sub-techniques (they appear via aggregate.py's parent
                promotion), and defensible-but-secondary readings. Counted
                neither as a miss when absent nor as a false positive when
                present.

Anything mapped that is in neither set is an "unexpected" mapping.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportGroundTruth:
    name: str          # human-readable report name
    pdf_glob: str      # glob under /data/uploads locating the source PDF
    core: dict[str, str]
    acceptable: dict[str, str]


# ---------------------------------------------------------------------------
# Meridian Grove (synthetic, `*sample_report._2.pdf`) — the original
# reference report. Linux/CI supply-chain intrusion escalating to domain
# compromise, surveillance, exfiltration, and ransomware.
# ---------------------------------------------------------------------------

_GROVE_CORE: dict[str, str] = {
    # §1 Initial access and reconnaissance
    "T1598": "recon email to the IT helpdesk soliciting DevOps staff names/emails (§1)",
    "T1566.001": "spearphishing email with a macro-enabled 'invoice' attachment (§1)",
    "T1204.002": "engineer opened the macro attachment, executing the loader (§1)",
    # §2 Supply chain + execution
    "T1195.001": "trojanized internal package (swift-metrics-shim) pulled by CI (§2)",
    "T1059.004": "invoked the CI container's shell interpreter to run recon (§2)",
    # §3 Linux foothold / persistence
    "T1053.003": "cron entry relaunching the loader every 30 min (§3)",
    "T1136.001": "created a new local account svc-metrics (§3)",
    "T1098.004": "appended their public key to a build account's authorized_keys (§3)",
    # §4 Privilege escalation + defense evasion
    "T1611": "broke out of the CI container onto the underlying host (§4)",
    "T1548.003": "abused a password-less sudoers rule to get a root shell (§4)",
    "T1036": "relocated tooling into paths disguised as log-rotation dirs (§4)",
    "T1070.006": "altered file modification timestamps to blend in (§4)",
    "T1070.003": "cleared shell history tied to their sessions (§4)",
    "T1612": "built a container image locally to avoid registry-pull alerts (§4)",
    "T1014": "installed a kernel-level rootkit hiding processes/files (§4)",
    # §5 Credential harvesting
    "T1003.008": "copied the host's /etc/shadow off the server (§5)",
    "T1110.002": "cracked the shadow file offline with dictionary+rule attacks (§5)",
    # §6 Lateral movement + domain compromise
    "T1078.002": "reused a cracked service-account password on the Windows domain (§6)",
    "T1021.004": "moved via SSH between hosts (§6)",
    "T1021.001": "moved via RDP between hosts (§6)",
    "T1021.006": "moved via WinRM between hosts (§6)",
    "T1558.003": "requested service tickets and cracked them offline — Kerberoasting (§6)",
    "T1558.001": "forged a golden ticket from the recovered krbtgt hash (§6)",
    # §7 Collection / surveillance
    "T1113": "captured periodic screenshots of CFO/COO workstations (§7)",
    "T1125": "captured webcam video from executive workstations (§7)",
    # §8 Exfiltration
    "T1560": "compressed and encrypted staged files locally before exfil (§8)",
    "T1041": "exfiltrated ~40 GB over a disguised command-and-control channel (§8)",
    # §9 Impact
    "T1486": "domain-wide ransomware encryption of shares/DBs (§9)",
    "T1490": "encrypted reachable backup catalogs (§9)",
    "T1657": "ransom demand + extortion threat to publish stolen data (§9)",
}

_GROVE_ACCEPTABLE: dict[str, str] = {
    # Parents of core sub-techniques (appear via parent promotion).
    "T1566": "parent — Phishing",
    "T1204": "parent — User Execution",
    "T1195": "parent — Supply Chain Compromise",
    "T1059": "parent — Command and Scripting Interpreter",
    "T1053": "parent — Scheduled Task/Job",
    "T1136": "parent — Create Account",
    "T1098": "parent — Account Manipulation (also: account added to Domain Admins, §6)",
    "T1548": "parent — Abuse Elevation Control Mechanism",
    "T1070": "parent — Indicator Removal",
    "T1003": "parent — OS Credential Dumping (also: krbtgt hash recovery, §6)",
    "T1110": "parent — Brute Force",
    "T1078": "parent — Valid Accounts",
    "T1558": "parent — Steal or Forge Kerberos Tickets",
    "T1021": "parent — Remote Services",
    "T1560.001": "sub — Archive via Utility (local compress+encrypt)",
    "T1036.005": "sub — Match Legitimate Name or Location (disguised paths)",
    # Defensible secondary readings.
    "T1105": "loader downloaded from actor infrastructure — Ingress Tool Transfer (§1)",
    "T1071": "C2/exfil disguised as analytics traffic — Application Layer Protocol (§8)",
    "T1071.001": "sub — Web Protocols (C2 to a CDN-like domain, §8)",
    "T1003.006": "ACL grant of replication rights enables DCSync (§6)",
    "T1484": "modified an OU ACL — Domain/Tenant Policy Modification (§6)",
    "T1074.001": "staged sensitive files locally before exfil — Local Data Staging (§8)",
    "T1039": "collected files from network shares (§8)",
    "T1552": "harvested cached package-registry credentials (§2)",
    "T1552.001": "sub — Credentials In Files (the shadow file is also a credential file, §5)",
    "T1555": "harvested cached credentials from a store (§2)",
    "T1677": "injected code ran inside the CI build via the poisoned package — Poisoned Pipeline Execution (§2)",
    "T1550": "parent — Use Alternate Authentication Material (golden ticket use, §6)",
    "T1550.003": "sub — Pass the Ticket (authenticating with the forged golden ticket, §6)",
}


# ---------------------------------------------------------------------------
# Meridian Health Partners (synthetic,
# `*Meridian_Health_Partners_Incident_Report.pdf`). Windows-domain intrusion:
# spearphish → macro → PowerShell downloader, domain discovery, LSASS +
# Kerberoasting, RDP/SMB lateral movement across 47 hosts, EDR disabling,
# staged exfil to cloud storage, ransomware + service stop + VSS deletion.
# 24 techniques embedded by the report author (T1078.002 appears twice in the
# authoring table — privilege escalation §4.4-4.5 and DC persistence §4.6 —
# one CORE entry here).
# ---------------------------------------------------------------------------

_HEALTH_CORE: dict[str, str] = {
    # §4.1 Initial access + execution + persistence
    "T1566.001": "spoofed clearinghouse email with malicious document attachment (§4.1)",
    "T1204.002": "user opens the attachment and enables macro content (§4.1)",
    "T1059.001": "macro triggers a PowerShell downloader for the second-stage payload (§4.1)",
    "T1053.005": "scheduled task on the initial host, later on domain controllers (§4.1, §4.6)",
    "T1547.001": "Registry Run key persistence on the initial host (§4.1)",
    # §4.2 Command and control
    "T1071.001": "HTTPS-based beaconing to C2 infrastructure (§4.2)",
    # §4.3 Discovery
    "T1082": "enumeration of local system configuration/installed software (§4.3)",
    "T1087.002": "enumeration of domain user accounts (§4.3)",
    "T1069.002": "enumeration of domain security groups and membership (§4.3)",
    "T1018": "enumeration of reachable systems to build the lateral-movement target list (§4.3)",
    # §4.4 Credential access + privilege escalation
    "T1003.001": "memory-dumping utility used against LSASS on the initial host (§4.4)",
    "T1558.003": "service ticket request + offline cracking of a service-account password (§4.4)",
    "T1078.002": "over-privileged service account gives Domain Admin-equivalent access; also DC persistence context (§4.4-4.6)",
    # §4.5 Lateral movement
    "T1021.001": "RDP between hosts with harvested credentials (§4.5)",
    "T1021.002": "administrative shares (ADMIN$/C$) used for lateral movement (§4.5)",
    "T1105": "remote-access utility transferred to multiple hosts for redundant access (§4.5)",
    "T1570": "tooling propagated across 47 hosts during lateral movement (§4.5)",
    # §4.6 Defense evasion + recovery inhibition
    # (v19.1: the old T1562.001 sub was promoted to standalone T1685)
    "T1685": "endpoint protection agents disabled/uninstalled prior to encryption (§4.6)",
    "T1490": "Volume Shadow Copy deletion domain-wide via GPO/remote execution (§4.6)",
    # §4.7 Collection + exfiltration
    "T1560.001": "files staged into password-protected compressed archives (§4.7)",
    "T1074.002": "archives staged in a temp directory on a corporate file server (§4.7)",
    "T1567.002": "~340 GB transferred to external commercial cloud storage over HTTPS (§4.7)",
    # §4.8 Impact
    "T1486": "ransomware encryption routine across endpoints/servers (§4.8)",
    "T1489": "backup-related and database services forcibly stopped before encryption (§4.8)",
}

_HEALTH_ACCEPTABLE: dict[str, str] = {
    # Parents of core sub-techniques (appear via parent promotion).
    "T1566": "parent — Phishing",
    "T1204": "parent — User Execution",
    "T1059": "parent — Command and Scripting Interpreter",
    "T1053": "parent — Scheduled Task/Job",
    "T1547": "parent — Boot or Logon Autostart Execution",
    "T1071": "parent — Application Layer Protocol",
    "T1087": "parent — Account Discovery",
    "T1069": "parent — Permission Groups Discovery",
    "T1003": "parent — OS Credential Dumping",
    "T1558": "parent — Steal or Forge Kerberos Tickets",
    "T1078": "parent — Valid Accounts",
    "T1021": "parent — Remote Services",
    "T1560": "parent — Archive Collected Data",
    "T1074": "parent — Data Staged",
    "T1567": "parent — Exfiltration Over Web Service",
    # Defensible secondary readings (several promoted 2026-07-16 after
    # reviewing the mapper's evidence quotes against the source — the report
    # author's 24-technique list undercounts what the narrative evidences).
    "T1518": "installed-software enumeration (§4.3) also reads as Software Discovery",
    "T1074.001": "archives are first assembled locally before the file-server staging (§4.7)",
    "T1041": "exfil rides the existing HTTPS channel — defensible alongside T1567.002 (§4.7)",
    "T1110.002": "ticket material 'offline-cracked over 48 hours using distributed cracking resources' (§4.4) — Password Cracking is explicitly evidenced",
    "T1657": "double extortion: ransom note 'threatening publication of the previously exfiltrated data' (§4.8) — Financial Theft covers extortion",
    "T1684.002": "'sender spoofed a known clearinghouse vendor domain' (§3, §4.1) — Email Spoofing is a fair reading of the look-alike domain",
}


REPORTS: dict[str, ReportGroundTruth] = {
    "meridian-grove": ReportGroundTruth(
        name="Meridian Grove",
        pdf_glob="/data/uploads/*sample_report._2.pdf",
        core=_GROVE_CORE,
        acceptable=_GROVE_ACCEPTABLE,
    ),
    "meridian-health": ReportGroundTruth(
        name="Meridian Health Partners",
        pdf_glob="/data/uploads/*Meridian_Health_Partners_Incident_Report.pdf",
        core=_HEALTH_CORE,
        acceptable=_HEALTH_ACCEPTABLE,
    ),
}

DEFAULT_REPORT = "meridian-grove"
