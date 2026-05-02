from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LTTBudget(BaseModel):
    alpha: float = 0.10
    delta_total: float = 0.10
    delta_eta: float = 0.03
    delta_LTT: float = 0.07
    K: int = 20
    B: int = 5
    ensemble_temperature: float = 0.7
    # documentation only — N_min = ceil(ln(1/delta_LTT) / (-ln(1-alpha)))
    N_min_formula: str = "ceil(ln(1/delta_LTT)/(-ln(1-alpha)))"
    c_human: float = 5.0
    c_llm: float = 0.001
    delta_bootstrap: float = 0.05  # confidence level for bootstrap eta upper bound — not part of delta_eta+delta_LTT split

    @model_validator(mode="after")
    def _check_delta_split(self) -> "LTTBudget":
        if not math.isclose(self.delta_eta + self.delta_LTT, self.delta_total, abs_tol=1e-9):
            raise ValueError(
                f"delta_eta ({self.delta_eta}) + delta_LTT ({self.delta_LTT}) "
                f"must equal delta_total ({self.delta_total})"
            )
        return self


class TopicConfig(BaseModel):
    topic_id: str
    family: Literal["DTA", "Intervention", "Prognosis", "Qualitative"]
    calib_frac: float = 0.5
    split_seed: int = 20260429


class CascadeRCConfig(BaseSettings):
    ltt: LTTBudget = LTTBudget()
    topics: list[TopicConfig] = []
    artefact_dir: Path = Path("artefacts/cascade_rc")
    sqlite_cache_path: Path = Path("artefacts/cascade_rc/llm_cache.db")
    ncbi_email: str = ""
    ncbi_api_key: str | None = None
    rrf_k: int = 60
    prompt_template_version: str = "v1"

    model_config = SettingsConfigDict(
        env_prefix="CRC_",
        env_nested_delimiter="__",
        env_file="cascade_rc.yaml",
        env_file_encoding="utf-8",
        extra="ignore",
    )
