"""Image engine: local mflux or remote host backend HTTP client."""

from __future__ import annotations

import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Protocol

ProgressFn = Callable[[dict[str, Any]], None]
from urllib.parse import urljoin

logger = logging.getLogger("studio.engine")

DATA_HOME = Path(os.environ.get("STUDIO_DATA_HOME", "/opt/ivoai"))


class EngineError(RuntimeError):
    pass


def _data_dirs() -> tuple[Path, Path, Path]:
    lora = Path(os.environ.get("STUDIO_LORA_DIR", DATA_HOME / "lora"))
    outputs = Path(os.environ.get("STUDIO_OUTPUTS_DIR", "/data/outputs"))
    uploads = Path(os.environ.get("STUDIO_UPLOADS_DIR", "/data/uploads"))
    for d in (outputs, uploads):
        d.mkdir(parents=True, exist_ok=True)
    # LoRA weights live on the host backend; the frontend must not require this dir.
    try:
        lora.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return lora, outputs, uploads


class ImageEngine(Protocol):
    def status(self) -> dict[str, Any]: ...
    def unload(self) -> None: ...
    def list_lora_files(self) -> list[str]: ...
    def generate(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 576,
        steps: int = 4,
        seed: int | None = None,
        quantize: int = 8,
        loras: list[dict[str, Any]] | None = None,
        ref_images: list[str] | None = None,
        on_progress: ProgressFn | None = None,
        mode: str = "gen",
        image_strength: float | None = None,
        guidance: float | None = None,
    ) -> Path: ...


class LocalMfluxEngine:
    """In-process mflux (dev / host all-in-one)."""

    def __init__(self) -> None:
        self._lora_dir, self._outputs_dir, self._uploads_dir = _data_dirs()

    def status(self) -> dict[str, Any]:
        from src.mflux_backend import backend

        st = backend.status()
        st.update({"mode": "local", "reachable": True, "url": None})
        return st

    def unload(self) -> None:
        from src.mflux_backend import backend

        backend.unload()

    def poll_progress(self) -> dict[str, Any]:
        from src.mflux_backend import last_progress

        return last_progress()

    def list_lora_files(self) -> list[str]:
        if not self._lora_dir.is_dir():
            return []
        return sorted(
            p.name for p in self._lora_dir.iterdir() if p.is_file() and p.suffix == ".safetensors"
        )

    def generate(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 576,
        steps: int = 4,
        seed: int | None = None,
        quantize: int = 8,
        loras: list[dict[str, Any]] | None = None,
        ref_images: list[str] | None = None,
        on_progress: ProgressFn | None = None,
        mode: str = "gen",
        image_strength: float | None = None,
        guidance: float | None = None,
    ) -> Path:
        from src.mflux_backend import MfluxBackendError, backend

        loras = loras or []
        ref_images = ref_images or []

        lora_paths: list[str] = []
        lora_scales: list[float] = []
        for item in loras:
            name = item.get("file") or ""
            if not name:
                continue
            path = self._lora_dir / Path(name).name
            if not path.is_file():
                raise EngineError(f"LoRA not found: {name}")
            lora_paths.append(str(path))
            lora_scales.append(float(item.get("scale") or 0.8))

        image_paths: list[str] | None = None
        if ref_images:
            image_paths = []
            for name in ref_images:
                path = self._uploads_dir / Path(name).name
                if not path.is_file():
                    raise EngineError(f"Reference image not found: {name}")
                image_paths.append(str(path))

        stamp = time.strftime("%Y%m%d-%H%M%S")
        # seed may still be random inside backend; filename uses placeholder then rename not needed
        out_path = self._outputs_dir / f"{stamp}-pending.png"

        try:
            result = backend.generate(
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
            )
        except MfluxBackendError as e:
            raise EngineError(str(e)) from e

        final = self._outputs_dir / f"{stamp}-{result['seed']}.png"
        if out_path != final:
            out_path.replace(final)
        return final


class RemoteHttpEngine:
    """Call host backend over HTTP (Docker hybrid mode)."""

    def __init__(self, base_url: str, timeout: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self._lora_dir, self._outputs_dir, self._uploads_dir = _data_dirs()

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        import json

        url = urljoin(self.base_url, path.lstrip("/"))
        data = None
        headers = {"Accept": "application/json"}
        secret = os.environ.get("STUDIO_BACKEND_SECRET") or ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise EngineError(f"Backend HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise EngineError(f"Backend unreachable at {self.base_url}: {e.reason}") from e

    def status(self) -> dict[str, Any]:
        try:
            remote = self._request("GET", "health")
            return {
                "mode": "remote",
                "url": self.base_url.rstrip("/"),
                "reachable": True,
                "mflux_available": remote.get("mflux_available", True),
                "loaded_mode": remote.get("loaded_mode"),
                "quantize": remote.get("quantize"),
                "lora_sig": remote.get("lora_sig"),
                "last_used": remote.get("last_used"),
            }
        except EngineError as e:
            return {
                "mode": "remote",
                "url": self.base_url.rstrip("/"),
                "reachable": False,
                "mflux_available": False,
                "error": str(e),
                "loaded_mode": None,
            }

    def unload(self) -> None:
        self._request("POST", "unload", {})

    def poll_progress(self) -> dict[str, Any]:
        try:
            return self._request("GET", "progress")
        except EngineError:
            return {}

    def list_lora_files(self) -> list[str]:
        try:
            data = self._request("GET", "loras")
        except EngineError:
            return []
        files = data.get("files") or []
        return [Path(name).name for name in files if name]

    def generate(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 576,
        steps: int = 4,
        seed: int | None = None,
        quantize: int = 8,
        loras: list[dict[str, Any]] | None = None,
        ref_images: list[str] | None = None,
        on_progress: ProgressFn | None = None,
        mode: str = "gen",
        image_strength: float | None = None,
        guidance: float | None = None,
    ) -> Path:
        import base64

        refs: list[dict[str, str]] = []
        for name in ref_images or []:
            path = self._uploads_dir / Path(name).name
            if not path.is_file():
                raise EngineError(f"Reference image not found: {name}")
            refs.append(
                {
                    "filename": path.name,
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            )

        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed,
            "quantize": quantize,
            "mode": mode,
            "image_strength": image_strength,
            "guidance": guidance,
            "loras": [
                {"file": Path(x["file"]).name, "scale": float(x.get("scale") or 0.8)}
                for x in (loras or [])
                if x.get("file")
            ],
            "ref_images": refs,
        }
        result = self._stream_generate(payload, on_progress=on_progress)
        if not result.get("ok"):
            raise EngineError(result.get("error") or "Backend generate failed")
        raw_b64 = result.get("image_base64")
        if not raw_b64:
            raise EngineError("Backend returned no image")
        name = result.get("image_file") or f"{time.strftime('%Y%m%d-%H%M%S')}-{result.get('seed', 'out')}.png"
        path = self._outputs_dir / Path(name).name
        path.write_bytes(base64.b64decode(raw_b64))
        return path

    def _stream_generate(
        self,
        payload: dict[str, Any],
        *,
        on_progress: ProgressFn | None,
    ) -> dict[str, Any]:
        import json
        from urllib.parse import urljoin
        import urllib.error
        import urllib.request

        url = urljoin(self.base_url, "generate")
        headers = {"Accept": "application/x-ndjson, application/json", "Content-Type": "application/json"}
        secret = os.environ.get("STUDIO_BACKEND_SECRET") or ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "ndjson" not in ctype and "json" in ctype:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
                buf = b""
                done: dict[str, Any] | None = None
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    buf += line
                    if not line.endswith(b"\n"):
                        continue
                    raw_line = buf.strip()
                    buf = b""
                    if not raw_line:
                        continue
                    try:
                        ev = json.loads(raw_line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    kind = ev.get("type")
                    if kind == "progress":
                        if on_progress:
                            on_progress(ev)
                    elif kind == "done":
                        done = ev
                    elif kind == "error":
                        raise EngineError(ev.get("error") or "Backend generate failed")
                if buf.strip():
                    try:
                        ev = json.loads(buf.decode("utf-8"))
                        if ev.get("type") == "done":
                            done = ev
                        elif ev.get("type") == "error":
                            raise EngineError(ev.get("error") or "Backend generate failed")
                    except json.JSONDecodeError:
                        pass
                if done is None:
                    raise EngineError("Backend stream ended without a result")
                return done
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise EngineError(f"Backend HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise EngineError(f"Backend unreachable at {self.base_url}: {e.reason}") from e


def create_engine() -> LocalMfluxEngine | RemoteHttpEngine:
    mode = (os.environ.get("ENGINE_MODE") or "local").strip().lower()
    if mode == "remote":
        url = os.environ.get("ENGINE_URL") or "http://127.0.0.1:8090"
        logger.info("Using remote engine at %s", url)
        return RemoteHttpEngine(url)
    logger.info("Using local mflux engine")
    return LocalMfluxEngine()


engine: LocalMfluxEngine | RemoteHttpEngine = create_engine()
