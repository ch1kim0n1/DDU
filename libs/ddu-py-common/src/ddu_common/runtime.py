"""Runtime helpers shared by Python DDU services."""
from __future__ import annotations

import os
from typing import Any


def model_mode() -> str:
    """Return normalized MODEL_MODE. Defaults to stub so empty env never loads GPU stacks."""
    return os.environ.get("MODEL_MODE", "stub").strip().lower() or "stub"


def model_mode_is_stub() -> bool:
    """True unless MODEL_MODE explicitly requests real weights/adapters."""
    return model_mode() not in {"real", "live", "production", "prod"}


def select_device() -> dict[str, Any]:
    """Detect CUDA/MPS/CPU. ML services must boot on CPU when GPU is unavailable."""
    info: dict[str, Any] = {
        "requested": os.environ.get("DDU_DEVICE", "auto").strip().lower() or "auto",
        "device": "cpu",
        "cuda_available": False,
        "mps_available": False,
    }
    requested = info["requested"]
    try:
        import torch  # type: ignore

        info["cuda_available"] = bool(torch.cuda.is_available())
        info["mps_available"] = bool(
            getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        )
        if requested in {"cuda", "gpu"} and info["cuda_available"]:
            info["device"] = "cuda"
        elif requested == "mps" and info["mps_available"]:
            info["device"] = "mps"
        elif requested == "cpu":
            info["device"] = "cpu"
        elif requested == "auto":
            if info["cuda_available"]:
                info["device"] = "cuda"
            elif info["mps_available"]:
                info["device"] = "mps"
            else:
                info["device"] = "cpu"
    except Exception as exc:  # noqa: BLE001 — torch optional
        info["detail"] = str(exc)
        info["device"] = "cpu"
    return info
