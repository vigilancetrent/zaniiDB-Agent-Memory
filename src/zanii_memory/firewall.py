"""Memory Firewall — protection against memory poisoning.

Indirect prompt injection is the top attack class against agents with
long-term memory: malicious content in an email/webpage/tool output gets
extracted into a persistent belief, compromising every future session. The
firewall screens every candidate memory BEFORE it can influence recall:

1. **Source binding** — each memory records which L0 messages produced it and
   the worst-trust channel among them (metadata: source_l0_ids, channel).
2. **Policy gate** — instruction-type memories derived from untrusted channels
   are ALWAYS quarantined (a webpage must never install a standing rule).
3. **Heuristic screen** — deterministic patterns for injection signatures
   (override attempts, exfiltration, concealment, credential fishing).
4. **LLM screen** — the extraction call already reads every memory; it flags
   suspicious ones in the same pass (zero extra cost).

Quarantined memories are excluded from every search/recall path until a human
releases or rejects them (`zanii-memory quarantine`, `/quarantine` routes,
dashboard). With the [provable] extra, every quarantine/release/reject emits a
hash-chained ledger receipt — an evidence-grade record of the incident and its
handling, suitable for the Zanii admissibility tooling (UAE Federal Law
46/2021 evidence workflows). Capability, not legal advice.
"""
from __future__ import annotations

import re

from .config import Settings

# Deterministic injection signatures. Belt-and-braces under the LLM screen:
# these must be high-precision (quarantine is friction), not high-recall.
_HEURISTICS: list[tuple[str, re.Pattern]] = [
    ("override-attempt", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,20}\b(instruction|rule|prompt)", re.I | re.S)),
    ("prompt-probe", re.compile(r"\b(system prompt|developer message|hidden instruction)", re.I)),
    ("identity-override", re.compile(r"\byou are (now|no longer)\b|\bnew (identity|persona) is\b", re.I)),
    ("concealment", re.compile(r"\b(do not|don't|never)\b.{0,30}\b(tell|inform|mention|reveal)\b.{0,30}\b(user|owner|human)", re.I | re.S)),
    ("exfiltration", re.compile(r"\b(send|post|forward|upload)\b.{0,60}\b(https?://|ftp://)", re.I | re.S)),
    ("credential-fishing", re.compile(r"\b(api[_ -]?key|password|secret|token|credential)s?\b.{0,40}\b(send|share|include|paste|reveal)", re.I | re.S)),
    ("obedience-install", re.compile(r"\b(always|must)\b.{0,30}\b(obey|comply with|follow)\b.{0,40}\b(this|these|the following|future)\b", re.I | re.S)),
    ("encoded-payload", re.compile(r"[A-Za-z0-9+/=]{120,}")),
]


def heuristic_screen(content: str) -> str | None:
    """Returns the matched signature name, or None when clean."""
    for name, pattern in _HEURISTICS:
        if pattern.search(content):
            return name
    return None


def trusted_channels(cfg: Settings) -> set[str]:
    return {c.strip() for c in cfg.firewall_trusted_channels.split(",") if c.strip()}


def decide_quarantine(
    cfg: Settings,
    mem_type: str,
    content: str,
    channels: set[str],
    llm_suspicion: str = "",
) -> str:
    """Returns the quarantine reason, or '' when the memory is clean.

    Order matters: LLM suspicion (most specific) > deterministic heuristics >
    channel policy. All three run regardless so tests can assert each layer.
    """
    if not cfg.firewall_enabled:
        return ""
    untrusted = channels - trusted_channels(cfg)
    if llm_suspicion:
        return f"screen:{llm_suspicion[:200]}"
    hit = heuristic_screen(content)
    if hit:
        return f"heuristic:{hit}"
    if untrusted and mem_type == "instruction":
        return f"policy:instruction-from-untrusted-channel({','.join(sorted(untrusted))})"
    if untrusted and cfg.firewall_strict:
        return f"policy:strict-untrusted-channel({','.join(sorted(untrusted))})"
    return ""
