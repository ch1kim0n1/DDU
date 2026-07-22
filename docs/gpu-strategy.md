# GPU Strategy

Local GPU is primary. Cloud GPU is fallback for overflow, large batch jobs, and CI.

## Local GPU (primary)

- **Target:** single workstation with NVIDIA GPU, ≥24GB VRAM (RTX 4090 / A5000 / A6000 class).
- **Driver:** NVIDIA driver ≥ 550, CUDA ≥ 12.4.
- **Container runtime:** NVIDIA Container Toolkit (`nvidia-container-toolkit`).
- **Compose:** GPU services declare `deploy.resources.reservations.devices` with `driver: nvidia`. See `infra/docker-compose.gpu.yml` (overlay).
- **Services on GPU:** `ddu-vision`, `ddu-ocr` (optional), `ddu-audio`, `ddu-geo`, `ddu-face` (CompreFace core).
- **CPU fallback for dev:** every ML service must boot on CPU (slow but functional) when no GPU is present. Use `device="cuda" if torch.cuda.is_available() else "cpu"` pattern. CI runs on CPU.

## Cloud GPU (fallback)

Use cases:
- **Overflow:** batch processing large investigations that exceed local VRAM or time budget.
- **Large models:** MMDetection custom models that don't fit local GPU.
- **CI:** GPU-required contract conformance tests (run nightly, not per-PR).

Providers (pick one, abstract behind interface):
- **RunPod** — on-demand, hourly, community cloud GPUs (A100, H100). Good for dev overflow.
- **Lambda Labs** — reserved H100 instances. Good for sustained workloads.
- **AWS p4/p5 instances** — if org already on AWS. Most expensive.

Abstraction: `ddu-vision`, `ddu-ocr`, `ddu-audio`, `ddu-geo` run as containers. Same image runs locally and on cloud GPU. Only the runtime context changes (kubeconfig, GPU node selector, secrets).

## Model Loading

- Models loaded once at service startup, kept in GPU memory for the process lifetime.
- No per-request model loading. No per-request disk reads of weights.
- Health check includes GPU memory availability: `/healthz` reports `DEGRADED` if free VRAM < threshold.

## Batching

- Perception services accept batched requests where possible (multiple images per Grounded SAM 2 call).
- `ddu-agent` orchestrates batch submission for video frame analysis.
- Max batch size configurable per service; default conservative for dev GPU.

## Failover

1. Service tries local GPU.
2. If OOM or unavailable → returns `503 DEGRADED` with `retry_after`.
3. `ddu-agent` (Phase 2+) can route to cloud GPU endpoint for overflow.
4. Cloud GPU endpoint = same service image, different deployment, registered in service discovery as `ddu-vision-cloud`.

## Dev Without GPU

Allowed for non-ML services and contract testing. ML services fall back to CPU with a startup log warning. Not suitable for production workloads.

## Cost Guardrails (cloud)

- Hard monthly budget alert via cloud provider billing.
- RunPod / Lambda: instances auto-terminate after idle threshold (configurable, default 30min).
- No persistent cloud GPU instances in dev.
