"""In-process mflux generation (host-only / local mode).

Imported by the local engine and the host backend. Must not be imported
inside the Docker API image at runtime for generation (image has no mflux).
"""

from __future__ import annotations

import gc
import logging
import os
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable

ProgressFn = Callable[[dict[str, Any]], None]


class _StepProgress:
    """mflux InLoop / BeforeLoop / AfterLoop callback → UI progress dicts."""

    def __init__(self, emit: ProgressFn, steps: int) -> None:
        self._emit = emit
        self.steps = max(int(steps), 1)

    def call_before_loop(self, **_kwargs: Any) -> None:
        self._emit(
            {
                "phase": "denoise",
                "step": 0,
                "steps": self.steps,
                "progress": 0.30,
                "message": f"Denoise 0/{self.steps}",
            }
        )

    def call_in_loop(self, t: int, config: Any = None, **_kwargs: Any) -> None:
        steps = self.steps
        if config is not None:
            steps = int(getattr(config, "num_inference_steps", None) or steps) or steps
        step = int(t) + 1
        frac = min(step / max(steps, 1), 1.0)
        self._emit(
            {
                "phase": "denoise",
                "step": step,
                "steps": steps,
                "progress": 0.30 + 0.60 * frac,
                "message": f"Denoise {step}/{steps}",
            }
        )

    def call_after_loop(self, **_kwargs: Any) -> None:
        self._emit({"phase": "decode", "progress": 0.92, "message": "Decoding image"})


_PROGRESS_LOCK = threading.Lock()
_LAST_PROGRESS: dict[str, Any] = {
    "progress": 0.0,
    "message": "Idle",
    "step": None,
    "steps": None,
    "phase": "idle",
    "active": False,
}


def last_progress() -> dict[str, Any]:
    with _PROGRESS_LOCK:
        return dict(_LAST_PROGRESS)


def _emit(fn: ProgressFn | None, payload: dict[str, Any]) -> None:
    with _PROGRESS_LOCK:
        _LAST_PROGRESS.update(payload)
        _LAST_PROGRESS["active"] = payload.get("phase") not in {None, "idle", "done"}
        _LAST_PROGRESS["updated"] = time.time()
    if fn is None:
        return
    try:
        fn(payload)
    except Exception:  # noqa: BLE001
        logger.exception("progress callback failed")


def _register_step_progress(model: Any, tap: _StepProgress) -> None:
    registry = getattr(model, "callbacks", None)
    if registry is None or not hasattr(registry, "register"):
        return
    registry.register(tap)


def _call_generate_image(model: Any, gen_kwargs: dict[str, Any]) -> Any:
    try:
        return model.generate_image(**gen_kwargs)
    except TypeError:
        alt = dict(gen_kwargs)
        alt.pop("num_inference_steps", None)
        alt["steps"] = gen_kwargs.get("num_inference_steps") or gen_kwargs.get("steps")
        return model.generate_image(**alt)


def _round16(n: float) -> int:
    return max(256, min(2048, int(round(n / 16.0)) * 16))


def _best_aspect_size(src_w: int, src_h: int, target_long: int) -> tuple[int, int]:
    """Uniform scale + 16px snap with least aspect error (no independent stretch)."""
    aspect = src_w / src_h
    target_long = max(256, min(1152, target_long))
    if src_w >= src_h:
        raw_w, raw_h = float(target_long), target_long / aspect
    else:
        raw_h, raw_w = float(target_long), target_long * aspect
    cands: list[tuple[float, int, int]] = []
    for w, h in (
        (_round16(raw_w), _round16(raw_h)),
        (_round16(raw_w), _round16(_round16(raw_w) / aspect)),
        (_round16(_round16(raw_h) * aspect), _round16(raw_h)),
    ):
        if h <= 0:
            continue
        err = abs((w / h) - aspect)
        cands.append((err, w, h))
    cands.sort()
    return cands[0][1], cands[0][2]


def _snap_edit_size(image_path: str, width: int, height: int) -> tuple[int, int]:
    """Match the source photo's aspect. Never stretch independently on each axis."""
    try:
        from PIL import Image

        with Image.open(image_path) as im:
            src_w, src_h = im.size
    except Exception:
        return _round16(width), _round16(height)
    if src_w < 16 or src_h < 16:
        return _round16(width), _round16(height)
    src_long = max(src_w, src_h)
    user_long = max(width, height)
    target_long = min(1152, max(user_long, min(src_long, 1152)))
    return _best_aspect_size(src_w, src_h, target_long)


def _install_negative(model: Any, text: str) -> Any:
    """Swap mflux's dummy negative (' ') when CFG is on (guidance > 1)."""
    orig = getattr(model, "_encode_prompt_pair", None)
    if orig is None:
        return None

    def wrapped(*, prompt: str, negative_prompt: str, guidance: float):  # type: ignore[no-untyped-def]
        neg = text if (guidance or 0) > 1.0 else negative_prompt
        return orig(prompt=prompt, negative_prompt=neg, guidance=guidance)

    model._encode_prompt_pair = wrapped  # type: ignore[method-assign]
    return orig


def _install_quality_negative(model: Any) -> Any:
    from src.system_prompts import QUALITY_NEGATIVE

    return _install_negative(model, QUALITY_NEGATIVE)


def _unregister_step_progress(model: Any, tap: _StepProgress) -> None:
    registry = getattr(model, "callbacks", None)
    if registry is None:
        return
    for name in ("in_loop", "before_loop", "after_loop", "interrupt"):
        bucket = getattr(registry, name, None)
        if isinstance(bucket, list) and tap in bucket:
            bucket.remove(tap)

logger = logging.getLogger("studio.mflux")

# Local-only: never talk to Hugging Face, even if the launcher env is missing.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

# Expected local snapshot name (not a download source).
DEFAULT_HF_REPO = "mlx-community/FLUX.2-klein-9B"
DEFAULT_MODEL_NAME = "FLUX.2-klein-9B"


def _data_home() -> Path:
    return Path(os.environ.get("STUDIO_DATA_HOME", "/opt/ivoai"))


def _unwrap_hf_snapshot(path: Path) -> Path | None:
    """Accept a snapshot dir or a huggingface hub wrapper (…/snapshots/<hash>)."""
    if not path.is_dir():
        return None
    snaps = path / "snapshots"
    if snaps.is_dir():
        kids = [p for p in snaps.iterdir() if p.is_dir()]
        kids.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if kids:
            return kids[0]
    return path


def _looks_like_flux_model(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "model_index.json").is_file():
        return True
    if any(path.glob("*.safetensors")) or any(path.glob("*/*.safetensors")):
        return True
    return False


def resolve_local_model_path() -> Path | None:
    """Prefer STUDIO_MODEL_DIR, then $STUDIO_DATA_HOME/models/FLUX.2-klein-9B."""
    candidates: list[Path] = []
    env = (os.environ.get("STUDIO_MODEL_DIR") or "").strip()
    if env:
        candidates.append(Path(env))
    root = _data_home() / "models"
    candidates.append(root / DEFAULT_MODEL_NAME)
    candidates.append(root / "models--mlx-community--FLUX.2-klein-9B")

    seen: set[Path] = set()
    for raw in candidates:
        try:
            raw = raw.resolve()
        except OSError:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        unwrapped = _unwrap_hf_snapshot(raw)
        if unwrapped and _looks_like_flux_model(unwrapped):
            return unwrapped
    return None


class MfluxBackendError(RuntimeError):
    pass


class MfluxBackend:
    """Lazy-load Flux2Klein / Edit; one mode loaded at a time.

    MLX streams are thread-local. Importing mflux, loading weights, generate,
    and unload must all run on the same long-lived thread or mx.eval raises
    ``There is no Stream(...) in current thread``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode: str | None = None
        self._model: Any = None
        self._lora_sig: tuple | None = None
        self._quantize: int | None = None
        self._last_used = 0.0
        self._available: bool | None = None
        self._jobs: queue.Queue[tuple[Any, tuple, dict, queue.Queue] | None] = queue.Queue()
        self._mlx_thread = threading.Thread(
            target=self._mlx_loop, name="studio-mlx", daemon=True
        )
        self._mlx_thread.start()

    def _mlx_loop(self) -> None:
        self._boot_mlx()
        logger.info("mlx worker thread ready (ident=%s)", threading.get_ident())
        while True:
            item = self._jobs.get()
            if item is None:
                return
            fn, args, kwargs, box = item
            try:
                box.put(("ok", fn(*args, **kwargs)))
            except Exception as e:  # noqa: BLE001
                box.put(("err", e))

    def _boot_mlx(self) -> None:
        """Create the default MLX streams on this thread before any generate."""
        try:
            import mlx.core as mx
            import mflux  # noqa: F401

            for device in (mx.default_device(), getattr(mx, "cpu", None), getattr(mx, "gpu", None)):
                if device is None:
                    continue
                try:
                    mx.default_stream(device)
                except Exception:  # noqa: BLE001
                    pass
            self._available = True
        except Exception:
            self._available = False
            logger.exception("mlx/mflux not available on worker thread")

    def _on_mlx(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is self._mlx_thread:
            return fn(*args, **kwargs)
        if not self._mlx_thread.is_alive():
            raise MfluxBackendError("MLX worker thread is not running")
        box: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        self._jobs.put((fn, args, kwargs, box))
        kind, payload = box.get()
        if kind == "err":
            raise payload
        return payload

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        return bool(self._on_mlx(self._probe_available))

    def _probe_available(self) -> bool:
        if self._available is not None:
            return self._available
        self._boot_mlx()
        return bool(self._available)

    def status(self) -> dict[str, Any]:
        local = resolve_local_model_path()
        return {
            "mflux_available": self.available,
            "loaded_mode": self._mode,
            "quantize": self._quantize,
            "lora_sig": list(self._lora_sig) if self._lora_sig else None,
            "last_used": self._last_used,
            "local_model": str(local) if local else None,
            "model_repo": DEFAULT_HF_REPO,
        }

    def unload(self) -> None:
        self._on_mlx(self._unload_impl)

    def _unload_impl(self) -> None:
        with self._lock:
            self._model = None
            self._mode = None
            self._lora_sig = None
            self._quantize = None
            gc.collect()
            try:
                import mlx.core as mx

                metal = getattr(mx, "metal", None)
                if metal is not None and hasattr(metal, "clear_cache"):
                    metal.clear_cache()
            except Exception:  # noqa: BLE001
                pass
            logger.info("mflux backend unloaded")

    def _ensure_model(
        self,
        mode: str,
        *,
        quantize: int,
        lora_paths: list[str],
        lora_scales: list[float],
    ) -> Any:
        if not self.available:
            raise MfluxBackendError(
                "mflux is not installed (requires macOS Apple Silicon). "
                "pip install mflux"
            )

        sig = (tuple(lora_paths), tuple(lora_scales))
        if (
            self._model is not None
            and self._mode == mode
            and self._lora_sig == sig
            and self._quantize == quantize
        ):
            self._last_used = time.time()
            return self._model

        self._model = None
        local = resolve_local_model_path()
        if local is None:
            raise MfluxBackendError(
                "No local FLUX.2-klein-9B snapshot under "
                f"{_data_home() / 'models'} (or STUDIO_MODEL_DIR). "
                "Import weights with ./launcher.sh --import-model DIR. "
                "Hugging Face downloads are disabled."
            )
        model_path = str(local)
        logger.info(
            "Loading mflux mode=%s quantize=%s loras=%s model_path=%s",
            mode,
            quantize,
            lora_paths,
            model_path,
        )

        from mflux.models.common.config import ModelConfig

        kwargs: dict[str, Any] = {
            "model_config": ModelConfig.flux2_klein_9b(),
            "quantize": quantize,
            "model_path": model_path,
        }
        if lora_paths:
            kwargs["lora_paths"] = lora_paths
            kwargs["lora_scales"] = lora_scales

        if mode == "gen":
            from mflux.models.flux2.variants import Flux2Klein

            self._model = Flux2Klein(**kwargs)
        elif mode == "edit":
            from mflux.models.flux2.variants import Flux2KleinEdit

            self._model = Flux2KleinEdit(**kwargs)
        else:
            raise MfluxBackendError(f"Unknown mode: {mode}")

        self._mode = mode
        self._lora_sig = sig
        self._quantize = quantize
        self._last_used = time.time()
        return self._model

    def generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        width: int = 1024,
        height: int = 576,
        steps: int = 4,
        seed: int | None = None,
        quantize: int = 8,
        lora_paths: list[str] | None = None,
        lora_scales: list[float] | None = None,
        image_paths: list[str] | None = None,
        on_progress: ProgressFn | None = None,
        mode: str | None = None,
        image_strength: float | None = None,
        guidance: float | None = None,
        system_mode: str | None = None,
        genital_override: bool = False,
    ) -> dict[str, Any]:
        """Run generation and save PNG to out_path. Returns {seed, path}."""
        if threading.current_thread() is not self._mlx_thread:
            return self._on_mlx(
                self.generate,
                prompt=prompt,
                out_path=out_path,
                width=width,
                height=height,
                steps=steps,
                seed=seed,
                quantize=quantize,
                lora_paths=lora_paths,
                lora_scales=lora_scales,
                image_paths=image_paths,
                on_progress=on_progress,
                mode=mode,
                image_strength=image_strength,
                guidance=guidance,
                system_mode=system_mode,
                genital_override=genital_override,
            )
        from src.system_prompts import with_system_prompt

        lora_paths = lora_paths or []
        lora_scales = lora_scales or []
        if len(lora_paths) != len(lora_scales):
            raise MfluxBackendError("lora_paths and lora_scales length mismatch")

        requested = (mode or "").strip().lower()
        if requested not in {"gen", "edit"}:
            requested = "edit" if image_paths else "gen"
        if requested == "edit" and not image_paths:
            raise MfluxBackendError("Edit mode requires a source image")
        mode = requested
        pose_ref = bool(image_paths and len(image_paths) >= 2)
        prompt = with_system_prompt(
            prompt,
            mode=system_mode or mode,
            pose_ref=pose_ref and (system_mode or mode) != "undress",
            genital_override=bool(genital_override),
        )
        seed = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if image_paths:
            snap_src = image_paths[-1] if pose_ref else image_paths[0]
            width, height = _snap_edit_size(snap_src, width, height)

        with self._lock:
            need_load = (
                self._model is None
                or self._mode != mode
                or self._lora_sig != (tuple(lora_paths), tuple(lora_scales))
                or self._quantize != quantize
            )
            _emit(
                on_progress,
                {
                    "phase": "load",
                    "progress": 0.08,
                    "message": "Loading weights…" if need_load else "Using loaded model",
                },
            )
            model = self._ensure_model(
                mode,
                quantize=quantize,
                lora_paths=lora_paths,
                lora_scales=lora_scales,
            )
            _emit(on_progress, {"phase": "encode", "progress": 0.22, "message": "Encoding prompt…"})

            tap = _StepProgress(lambda p: _emit(on_progress, p), steps)
            _register_step_progress(model, tap)
            sys_mode = (system_mode or mode or "").strip().lower()
            # Pose: skip "deformed / grotesque" (fights gape) but keep yellow-cum lock.
            # Undress: no negative (guidance 1.0 anyway).
            if sys_mode == "undress":
                prev_encode = None
            elif sys_mode == "pose" or (mode == "edit" and sys_mode != "gen"):
                from src.system_prompts import SEMEN_NEGATIVE

                prev_encode = _install_negative(model, SEMEN_NEGATIVE)
            else:
                prev_encode = _install_quality_negative(model)
            try:
                if guidance is None:
                    if sys_mode == "undress":
                        guidance = 1.0
                    elif mode == "edit":
                        guidance = 2.0
                    else:
                        guidance = 1.4
                gen_kwargs: dict[str, Any] = {
                    "seed": seed,
                    "prompt": prompt,
                    "num_inference_steps": steps,
                    "guidance": float(guidance),
                }
                gen_kwargs["width"] = width
                gen_kwargs["height"] = height
                if mode == "edit":
                    gen_kwargs["image_paths"] = image_paths
                    # Flux2KleinEdit is instruction + refs, not SD img2img.
                    # Passing image_strength ~0.75 on 4 distilled steps starts
                    # at the last step → mosaic / garbage and progress "4/4".
                elif image_paths:
                    gen_kwargs["image_path"] = image_paths[0]
                    gen_kwargs["image_strength"] = (
                        float(image_strength) if image_strength is not None else 0.55
                    )

                try:
                    image = _call_generate_image(model, gen_kwargs)
                except ValueError as e:
                    if lora_paths and "matmul" in str(e).lower():
                        logger.warning("LoRA matmul failed (%s); retrying without LoRAs", e)
                        _unregister_step_progress(model, tap)
                        model = self._ensure_model(
                            mode, quantize=quantize, lora_paths=[], lora_scales=[]
                        )
                        _register_step_progress(model, tap)
                        image = _call_generate_image(model, gen_kwargs)
                    else:
                        raise
            finally:
                if prev_encode is not None:
                    model._encode_prompt_pair = prev_encode
                _unregister_step_progress(model, tap)

            _emit(on_progress, {"phase": "save", "progress": 0.97, "message": "Saving image…"})

            if hasattr(image, "save"):
                image.save(str(out_path))
            elif hasattr(image, "image"):
                image.image.save(str(out_path))
            else:
                from PIL import Image as PILImage

                if isinstance(image, PILImage.Image):
                    image.save(str(out_path))
                else:
                    raise MfluxBackendError(f"Unknown image return type: {type(image)}")

            self._last_used = time.time()
            logger.info("Saved %s", out_path)
            return {"seed": seed, "path": str(out_path), "file": out_path.name}


# Shared singleton for in-process use
backend = MfluxBackend()
