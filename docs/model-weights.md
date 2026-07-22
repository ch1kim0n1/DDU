# Model Weights Strategy

Pinned, content-addressed, reproducible. Every ML service reports the exact weights it loaded via `/versionz` and OpenLineage events.

## Principles

1. **Pinned versions.** No `latest`, no floating tags. Every model has a fixed version + a fixed download URL + a fixed sha256.
2. **Content-addressed.** Weights stored in MinIO under `ddu-models/<service>/<model_name>/<version>/<file>` with sha256 verification.
3. **Reproducible inference.** Same input + same weights + same code = same output. Required for evidence provenance.
4. **No silent upgrades.** Upgrading a model is a deliberate change: bump version, re-run contract conformance tests, re-process affected investigations where required.
5. **Air-gap capable.** All weights downloadable once, then served from MinIO. No runtime calls to HuggingFace/S3 upstream.

## Bucket Layout

```
s3://ddu-models/
└── <service>/
    └── <model_name>/
        └── <version>/
            ├── weights.bin
            ├── config.json
            └── manifest.json     # sha256, source_url, license, downloaded_at
```

Example:
```
s3://ddu-models/ddu-vision/grounded-sam-2/0.4.0/
├── sam2_hiera_large.pt
├── grounded_sam2_config.yaml
└── manifest.json
```

## manifest.json schema

```json
{
  "service": "ddu-vision",
  "model_name": "grounded-sam-2",
  "model_version": "0.4.0",
  "files": [
    {
      "path": "sam2_hiera_large.pt",
      "sha256": "abc123...",
      "size_bytes": 2450000000
    }
  ],
  "source_url": "https://huggingface.co/IDEA-Research/.../resolve/main/sam2_hiera_large.pt",
  "license": "Apache-2.0",
  "downloaded_at": "2026-07-21T12:00:00Z",
  "downloaded_by": "ddu-storage bootstrap script"
}
```

## Pinned Versions (initial)

| Service | Model | Version | Source | License |
|---------|-------|---------|--------|---------|
| `ddu-vision` | Grounded SAM 2 (SAM2 Hiera Large + GroundingDINO-T) | 0.4.0 | IDEA-Research HF repo | Apache-2.0 |
| `ddu-ocr` | PaddleOCR PP-OCRv4 det + rec (en) | 2.7.0 | PaddlePaddle/PaddleOCR release | Apache-2.0 |
| `ddu-audio` | Whisper large-v3 | 3.0.0 | openai/whisper HF | MIT |
| `ddu-geo` | GeoCLIP ViT-B/16 | 1.0.0 | VicenteVivan/geo-clip release | MIT |
| `ddu-face` | CompreFace bundled models (ArcFace) | 1.2.0 | exadel-inc/CompreFace release | Apache-2.0 |

MMDetection (Phase 2): custom-trained models. Each model gets its own versioned directory under `ddu-models/ddu-vision/mmdetection/<custom_name>/<version>/`.

## Bootstrap Script (planned)

`infra/scripts/bootstrap-models.sh` — runs once after `docker compose up`. Downloads each pinned model from its source, verifies sha256, uploads to MinIO `ddu-models` bucket, writes `manifest.json`. Idempotent: skips files already present with matching hash.

ML services on startup:
1. Read `MODEL_VERSION` env (defaults to pinned version).
2. Pull from MinIO `ddu-models/<service>/<model>/<version>/`.
3. Verify sha256 against `manifest.json`.
4. Load into memory / GPU.
5. Report `model_version` in `/versionz` and every lineage event.

## Provenance

Every observation produced by an ML service carries:
- `model` field in `Provenance`
- `model_version` field in `Provenance`
- `input_evidence_ids` chain back to the source evidence

This allows retroactive reprocessing when a model is upgraded: query all observations produced by model version X, re-run with version Y, present diff to investigator.
