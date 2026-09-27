"""Wake gating and text cleanup. No network or model dependencies."""
from __future__ import annotations

import re
import time


def speakable(text: str, limit: int = 1600) -> str:
    text = re.sub(r"```[\s\S]*?```", " Code is available in the chat. ", text)
    text = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "link in the chat", text)
    text = re.sub(r"(?m)^\s*[#>*-]+\s*", "", text)
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text.rfind(". ", limit // 2, limit - 40)
        text = text[:cut + 1 if cut != -1 else limit - 40] + " The rest is in the chat."
    return text


class WakeGate:
    def __init__(self, name: str = "jake", grace: float = 12):
        self.pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.I)
        self.grace = grace
        self.armed_until = 0.0

    def reset(self) -> None:
        self.armed_until = 0.0

    def accept(self, text: str, now: float | None = None, words: list | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        text = text.strip()
        if self.pattern.search(text):
            if words is not None:
                confidence = [w.get("conf", 0) for w in words if self.pattern.fullmatch(w.get("word", ""))]
                if not confidence or max(confidence) < .65:
                    return None
            text = self.pattern.sub("", text, count=1)
            text = re.sub(r"^\s*(?:hey|hi|hello|okay|ok)[,\s]+", "", text, flags=re.I).strip(" ,.!?")
            if not text:
                self.armed_until = now + self.grace
                return ""
            self.reset()
            return text
        if text and now < self.armed_until:
            self.reset()
            return text
        return None


def model_choice(command: str, models: list[str]) -> str | None:
    text = command.lower().strip(" .!?")
    if not re.match(r"^(?:please\s+)?(?:switch|change|use|select|set)\b", text):
        return None
    # Exact catalog IDs support future model families without code changes.
    for model in sorted(models, key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(model.lower()) + r"(?!\w)", text):
            return model
    if not re.search(r"\b(?:model|astra|astro|astral|sol|soul|seoul|luna|lunar|terra|tara|gpt|g p t)\b", text):
        return None
    versions = [(r"five\s+(?:point|dot)\s+six|5[ .]6", "5.6"),
                (r"five\s+(?:point|dot)\s+five|5[ .]5", "5.5"), (r"\bsix\b|\b6\b", "6")]
    version = next((v for p, v in versions if re.search(p, text)), None)
    aliases = {"astra": r"\b(?:astra|astro|astral)\b", "sol": r"\b(?:sol|soul|seoul)\b",
               "luna": r"\b(?:luna|lunar)\b", "terra": r"\b(?:terra|tara)\b"}
    family = next((f for f, p in aliases.items() if re.search(p, text)), None)
    candidates = [m for m in models if (not family or m.endswith("-" + family)) and
                  (not version or m == "gpt-" + version or m.startswith("gpt-" + version + "-"))]
    return candidates[0] if candidates and (family or version) and (family or len(candidates) == 1) else ""


def effort_choice(command: str, efforts: list[str]) -> str | None:
    text = command.lower().strip(" .!?")
    if not re.match(r"^(?:please\s+)?(?:switch|change|use|select|set)\b", text):
        return None
    if not re.search(r"\b(?:reasoning|effort|thinking)\b", text):
        return None
    aliases = {"xhigh": r"\b(?:extra\s*high|x\s*high|xhigh)\b"}
    for effort in sorted(set(efforts), key=len, reverse=True):
        pattern = aliases.get(effort, r"\b" + re.escape(effort) + r"\b")
        if re.search(pattern, text):
            return effort
    return ""
