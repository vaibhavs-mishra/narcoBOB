"""Runtime configuration, read from environment variables (and `src/.env`).

Every variable here is documented in `src/.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# `src/` — every relative path in the config is resolved against it.
SRC_DIR = Path(__file__).resolve().parents[2]


def _floats(value: object) -> object:
    """Accept `"0.35,0.25"` from the environment as well as a real list."""
    if isinstance(value, str):
        return [float(part) for part in value.split(",")]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SRC_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    db_path: Path = Field(Path("var/narcobob.db"), alias="NARCOBOB_DB_PATH")
    area_name: str = Field("Amritsar–Tarn Taran border belt", alias="NARCOBOB_AREA_NAME")
    # lat_min, lon_min, lat_max, lon_max
    area_bbox: Annotated[tuple[float, float, float, float], NoDecode] = Field(
        (31.20, 74.50, 31.90, 75.20), alias="NARCOBOB_AREA_BBOX"
    )
    h3_res: int = Field(7, alias="NARCOBOB_H3_RES", ge=4, le=10)
    bucket_sim_seconds: int = Field(86_400, alias="NARCOBOB_BUCKET_SIM_SECONDS", gt=0)
    sim_seconds_per_wall_second: float = Field(
        28_800, alias="NARCOBOB_SIM_SECONDS_PER_WALL_SECOND", gt=0
    )
    backfill_buckets: int = Field(60, alias="NARCOBOB_BACKFILL_BUCKETS", ge=0)
    scenario: str = Field("demo_border_surge", alias="NARCOBOB_SCENARIO")
    seed: int = Field(42, alias="NARCOBOB_SEED")
    score_interval_s: float = Field(2.0, alias="NARCOBOB_SCORE_INTERVAL_S", gt=0)
    # accel, div, spill, gi
    weights: Annotated[tuple[float, float, float, float], NoDecode] = Field(
        (0.35, 0.25, 0.20, 0.20), alias="NARCOBOB_WEIGHTS"
    )
    # watch, high, critical
    thresholds: Annotated[tuple[int, int, int], NoDecode] = Field(
        (65, 82, 90), alias="NARCOBOB_THRESHOLDS"
    )
    alert_cooldown_s: float = Field(120, alias="NARCOBOB_ALERT_COOLDOWN_S", ge=0)
    alert_coalesce_s: float = Field(15, alias="NARCOBOB_ALERT_COALESCE_S", ge=0)
    agents_mode: Literal["bob", "fallback"] = Field("bob", alias="NARCOBOB_AGENTS_MODE")
    bob_bin: str = Field("bob", alias="BOB_BIN")
    bob_agent_timeout_s: float = Field(180, alias="BOB_AGENT_TIMEOUT_S", gt=0)
    bob_api_key: SecretStr | None = Field(None, alias="BOB_API_KEY")
    api_port: int = Field(8000, alias="NARCOBOB_API_PORT")
    mcp_port: int = Field(8765, alias="NARCOBOB_MCP_PORT")
    sim_port: int = Field(8001, alias="NARCOBOB_SIM_PORT")
    sim_autostart: bool = Field(True, alias="NARCOBOB_SIM_AUTOSTART")
    record: bool = Field(True, alias="NARCOBOB_RECORD")
    replay_file: Path = Field(Path("recordings/demo_golden.jsonl"), alias="NARCOBOB_REPLAY_FILE")
    replay_speed: float = Field(1.0, alias="NARCOBOB_REPLAY_SPEED", gt=0)

    @field_validator("area_bbox", "weights", "thresholds", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _floats(value)

    def resolve(self, path: Path) -> Path:
        """Resolve a config path relative to `src/`."""
        return path if path.is_absolute() else SRC_DIR / path

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def scenario_file(self) -> Path:
        return SRC_DIR / "scenarios" / f"{self.scenario}.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def public_config(settings: Settings) -> dict[str, object]:
    """The subset of config that the UI and agents may see (`PublicConfig`)."""
    accel, div, spill, gi = settings.weights
    watch, high, critical = settings.thresholds
    return {
        "area_name": settings.area_name,
        "bbox": list(settings.area_bbox),
        "h3_res": settings.h3_res,
        "bucket_sim_seconds": settings.bucket_sim_seconds,
        "weights": {"accel": accel, "div": div, "spill": spill, "gi": gi},
        "thresholds": {"watch": watch, "high": high, "critical": critical},
        "agents_mode": settings.agents_mode,
    }
