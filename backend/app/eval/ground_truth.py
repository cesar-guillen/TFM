"""Hand-labelled ATT&CK ground truth for the Meridian Grove synthetic report
(`data/uploads/*sample_report._2.pdf`), the reference report for the mapping
eval harness.

Labelled by a human reading the narrative (sections referenced as §N). It is a
judgment call and deliberately editable — the harness reads these two sets, it
does not hardcode them, so revise as understanding improves. Keep the evidence
note on each entry: it is why the label is defensible and where to look in the
report.

- `CORE`     — unambiguous adversary activity a good mapping MUST recover.
              Recall is scored against this set.
- `ACCEPTABLE`— reasonable if mapped but not required: parents of core
              sub-techniques (they appear via aggregate.py's parent promotion),
              and defensible-but-secondary readings. Counted neither as a miss
              when absent nor as a false positive when present.

Anything mapped that is in neither set is an "unexpected" mapping — a candidate
false positive for a human to review (and possibly promote into ACCEPTABLE).
"""

CORE: dict[str, str] = {
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

ACCEPTABLE: dict[str, str] = {
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
