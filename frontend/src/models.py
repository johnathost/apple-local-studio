"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoraPin(BaseModel):
    id: str
    scale: float | None = None


class ComposeRequest(BaseModel):
    scene: dict[str, Any] = Field(default_factory=dict)
    raw_prompt: str | None = None
    manual_loras: list[LoraPin] = Field(default_factory=list)
    max_loras: int | None = None
    include_triggers: bool = True
    mode: str = "gen"


class ComposeResponse(BaseModel):
    prompt: str
    tags: list[str]
    loras: list[dict[str, Any]]
    scene: dict[str, Any]


class GenerateRequest(BaseModel):
    scene: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    raw_prompt: str | None = None
    manual_loras: list[LoraPin] = Field(default_factory=list)
    max_loras: int | None = None
    include_triggers: bool = True
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    seed: int | None = None
    quantize: int | None = None
    # Basenames of files already uploaded to the frontend container
    image_paths: list[str] = Field(default_factory=list)
    mode: str = "gen"
    image_strength: float | None = None
    guidance: float | None = None


class JobResponse(BaseModel):
    id: str
    status: str
    progress: float
    message: str
    step: int | None = None
    steps: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
