from __future__ import annotations

import pytest
import pandas as pd

from cascade_rc.synthetic.beta_mixture import generate_paper_running_example
from cascade_rc.config import CascadeRCConfig, TopicConfig


@pytest.fixture(scope="session")
def synthetic_df() -> pd.DataFrame:
    return generate_paper_running_example(n=10_000, seed=0)


@pytest.fixture(scope="session")
def tiny_topic_df() -> pd.DataFrame:
    return generate_paper_running_example(n=50, seed=42)


@pytest.fixture(scope="session")
def crc_config_test() -> CascadeRCConfig:
    return CascadeRCConfig(
        ncbi_email="test@example.com",
        topics=[
            TopicConfig(
                topic_id="CD008874",
                family="DTA",
                calib_frac=0.5,
                split_seed=20260429,
            )
        ],
    )
