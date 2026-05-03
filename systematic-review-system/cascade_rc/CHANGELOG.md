# Changelog

All notable changes to cascade_rc will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Tech Debt

- **`_compute_wss` / `_find_theta_hat_idx` duplicated** across
  `cascade_rc/ablations/budget_split.py` and `cascade_rc/ablations/walk_ordering.py`.
  Both helpers are currently identical. Extract to `cascade_rc/ablations/_common.py`
  once a third caller appears — premature extraction now would lock both modules'
  evolution together before their signatures have stabilised.

## [0.0.1] - 2026-04-29

### Added
- `cascade_rc/config.py`: `CascadeRCConfig`, `LTTBudget`, `TopicConfig` pydantic-settings schema
- `cascade_rc/synthetic/beta_mixture.py`: `generate_paper_running_example` — synthetic beta-mixture data matching paper §3
- `tests/conftest.py`: `synthetic_df`, `tiny_topic_df`, `crc_config_test` pytest fixtures
- `pyproject.toml`: pinned `[project.optional-dependencies] cascade_rc` extras
