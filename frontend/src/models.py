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
    # Field path the user just changed, e.g. "act.primary". Last-write wins.
    winner: str | None = None
    # True when the user attached a pose reference photo for this compose.
    pose_ref: bool = False


class ComposeResponse(BaseModel):
    prompt: str
    tags: list[str]
    loras: list[dict[str, Any]]
    scene: dict[str, Any]
    dropped: list[str] = Field(default_factory=list)
    blocked: dict[str, list[str]] = Field(default_factory=dict)


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
    # Optional second upload: pose/camera plate (edit restage)
    pose_path: str | None = None
    mode: str = "gen"
    image_strength: float | None = None
    guidance: float | None = None
    winner: str | None = None


class PromoteRequest(BaseModel):
    name: str


class RecipeRequest(BaseModel):
    identity: str
    undress: bool = False
    scene_id: str | None = None
    extras: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    seed: int | None = None
    quantize: int | None = None
    guidance: float | None = None
    max_loras: int | None = None
    notes: str | None = None
    # Re-run one planned step. keep_steps are the frames before it.
    retry_step: int | None = None
    keep_steps: list[dict[str, Any]] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    status: str
    progress: float
    message: str
    step: int | None = None
    steps: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
