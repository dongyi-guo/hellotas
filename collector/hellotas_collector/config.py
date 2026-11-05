"""Loading collector/sources.yaml and finding the site root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML


@dataclass
class Config:
    user_agent: str
    timezone: str = "Australia/Hobart"
    horizon_days: int = 240
    min_relevance: int = 60
    delay_seconds: float = 1.5
    default_image: str = ""
    ai: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)

    @property
    def ai_enabled(self) -> bool:
        """The AI is used only when switched on in sources.yaml (ai.enabled) and a key is available."""
        return bool(self.ai.get("enabled", False))

    def enabled_sources(self, only: list[str] | None = None) -> list[dict]:
        chosen = [s for s in self.sources if s.get("enabled", True)]
        if only:
            chosen = [s for s in self.sources if s["id"] in only]  # naming a source runs it even if disabled
        return chosen

    def source(self, source_id: str) -> dict | None:
        return next((s for s in self.sources if s["id"] == source_id), None)


def find_root(start: Path | None = None) -> Path:
    """The Hugo site root: the nearest folder upwards with hugo.toml."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / "hugo.toml").exists():
            return folder
    raise FileNotFoundError("Couldn't find hugo.toml; run inside the site or pass --root")


def load(path: Path) -> Config:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    ids = [s.get("id") for s in sources]
    if len(ids) != len(set(ids)) or not all(ids):
        raise ValueError(f"{path}: every source needs a unique id")
    return Config(
        user_agent=data.get("user_agent") or "hellotas-collector/1.0",
        timezone=data.get("timezone", "Australia/Hobart"),
        horizon_days=int(data.get("horizon_days", 240)),
        min_relevance=int(data.get("min_relevance", 60)),
        delay_seconds=float(data.get("delay_seconds", 1.5)),
        default_image=data.get("default_image") or "",
        ai=data.get("ai") or {},
        sources=sources,
    )
