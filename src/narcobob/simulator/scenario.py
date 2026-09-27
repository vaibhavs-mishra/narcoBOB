"""Scenario files (`src/scenarios/<name>.yaml`): the synthetic world the simulator draws from."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from narcobob.common.schemas import EventType


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Area(_Model):
    bbox: tuple[float, float, float, float]
    h3_res: int = 7


class Centre(_Model):
    lat: float
    lon: float
    weight: float
    sigma_km: float


class EnforcementField(_Model):
    mode: Literal["gaussian_mix"] = "gaussian_mix"
    min: float = 0.3
    max: float = 1.0
    sigma_km: float = 10.0


class Background(_Model):
    centres: list[Centre]
    rural_rate: float  # events/cell/day, all types together
    rates_per_day: dict[EventType, float]  # area totals, before enforcement thinning
    weekly_od_bump: float = 1.0  # Saturday/Sunday overdose multiplier
    enforcement_field: EnforcementField = Field(default_factory=EnforcementField)


class Source(_Model):
    id: str
    lat: float | None = None
    lon: float | None = None


class Sources(_Model):
    hospital: list[Source]
    police: list[Source]

    @field_validator("hospital", "police", mode="before")
    @classmethod
    def _bare_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return [{"id": v} if isinstance(v, str) else v for v in value]
        return value


class InjectionSpec(_Model):
    id: str
    kind: Literal["surge", "outage", "raid"]
    at_day: int
    lat: float | None = None
    lon: float | None = None
    radius_cells: int = 1
    around: str | None = None  # surge on the rings around another injection's centre
    ring: int = 1
    types: list[EventType] = Field(default_factory=lambda: ["overdose"])
    multiplier: float = 1.0
    absolute: float | None = None  # N extra events in total, spread over ramp_days
    ramp_days: int = 1
    source: str | None = None  # outage: "hospital:<id>"
    duration_days: int | None = None  # outage/raid; surges hold once ramped


class Scenario(_Model):
    name: str
    start_date: date = date(2026, 7, 1)
    area: Area
    background: Background
    sources: Sources
    injections: list[InjectionSpec] = Field(default_factory=list)
    live_injectable: list[str] = Field(default_factory=list)
    auto_injections: bool = False

    def injection(self, injection_id: str) -> InjectionSpec:
        for inj in self.injections:
            if inj.id == injection_id:
                return inj
        raise KeyError(injection_id)


def load_scenario(path: Path) -> Scenario:
    with path.open(encoding="utf-8") as fh:
        return Scenario.model_validate(yaml.safe_load(fh))
