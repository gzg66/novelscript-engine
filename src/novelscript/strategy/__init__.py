from __future__ import annotations

from typing import Protocol


class AdaptationStrategy(Protocol):
    mode_id: str

    def input_manifest(self) -> dict: ...

    def index_stages(self) -> list[str]: ...

    def s0_stages(self) -> list[str]: ...

    def macro_stages(self) -> list[str]: ...

    def micro_stages(self) -> list[str]: ...


class StandardRefinementStrategy:
    """M1 — MVP implementation."""

    mode_id = "M1"

    def input_manifest(self) -> dict:
        return {"primary": "novel.txt", "rights_basis": "required"}

    def index_stages(self) -> list[str]:
        return ["chapters", "source_lines", "must_keep_scenes", "source_cards"]

    def s0_stages(self) -> list[str]:
        return ["project_preference", "adaptation_brief", "source_cards", "story_engine", "adaptation_strategy"]

    def macro_stages(self) -> list[str]:
        return ["series_premise", "character_bible", "season_map"]

    def micro_stages(self) -> list[str]:
        return ["episode_list", "beat_sheet", "script", "pilot_review"]

    def pre_stages(self) -> list[str]:
        return ["P0", "P1", "P3", "P6"]


class DeepAdaptationStrategy:
    """M2 — placeholder for Phase 2."""

    mode_id = "M2"

    def input_manifest(self) -> dict:
        return {"primary": "novel.txt", "experience_anchor": "required"}

    def index_stages(self) -> list[str]:
        return ["chapters", "source_lines", "must_keep_scenes", "experience_anchor"]

    def s0_stages(self) -> list[str]:
        return ["adaptation_brief", "story_engine", "experience_anchor", "adaptation_freedom_map"]

    def macro_stages(self) -> list[str]:
        return ["series_premise", "character_bible", "season_map"]

    def micro_stages(self) -> list[str]:
        return ["episode_list", "beat_sheet", "script"]


def get_strategy(mode: str) -> AdaptationStrategy:
    if mode == "M2":
        return DeepAdaptationStrategy()
    return StandardRefinementStrategy()
