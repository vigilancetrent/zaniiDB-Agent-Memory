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
# English patterns run against a de-obfuscated copy (spaced letters collapsed);
# Arabic patterns run against the raw text. The LLM screen remains the
# language-agnostic catch-all — see docs/firewall-redteam.md.
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

# Arabic injection signatures (high-value verbs, matched on raw text). Closes
# the 0/7 Arabic gap the 2026-07-20 red-team measured on the English-only set.
_HEURISTICS_AR: list[tuple[str, re.Pattern]] = [
    ("override-attempt", re.compile(r"تجاهل|انسَ?\b.{0,20}(القواعد|التعليمات)|اعتبر.{0,20}تعليماتك")),
    ("identity-override", re.compile(r"أنت الآن\b.{0,30}(جديد|بلا قيود|حر)")),
    ("concealment", re.compile(r"لا\s*تخبر|لا\s*تُخبر|بدون\s*علم")),
    ("exfiltration", re.compile(r"(أرسل|حوّل|حول|انشر).{0,60}(https?://|رابط|الأرشيف الخارجي)")),
    ("credential-fishing", re.compile(r"(كلمة\s*(المرور|مرور)|مفتاح\s*API|سر).{0,40}(أدرج|أرسل|شارك)")),
    ("obedience-install", re.compile(r"(يجب|عليك).{0,30}(الالتزام|تلتزم).{0,40}(القادمة|المستقبل|كل\s*المحادثات)")),
]

# Spaced-letter obfuscation: "I G N O R E" -> "IGNORE". Collapses single ASCII
# letters separated only by spaces so the English patterns still see the word.
_SPACED = re.compile(r"\b(?:[A-Za-z]\s){2,}[A-Za-z]\b")


def _deobfuscate(content: str) -> str:
    return _SPACED.sub(lambda m: m.group(0).replace(" ", ""), content)


def heuristic_screen(content: str) -> str | None:
    """Returns the matched signature name, or None when clean."""
    text = _deobfuscate(content)
    for name, pattern in _HEURISTICS:
        if pattern.search(text):
            return name
    for name, pattern in _HEURISTICS_AR:
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
