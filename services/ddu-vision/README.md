# ddu-vision

Grounded SAM 2 object detection service. Implements:
- `GET /healthz`
- `GET /versionz`
- `POST /v1/detect`

## Run

```bash
pip install -e ../../libs/ddu-py-common
pip install -e '.[model]'
python app.py
```

The adapter loads Grounding DINO plus SAM 2 lazily on the first request. CUDA
is selected when `torch.cuda.is_available()`; otherwise the service logs a
warning and runs on CPU.

## Model loading

The default `MODEL_SOURCE=huggingface` downloads
`IDEA-Research/grounding-dino-tiny` and `facebook/sam2.1-hiera-small`.
Artifacts are cached under
`~/.cache/ddu/models/ddu-vision/grounded-sam-2/0.4.0/`.

For `MODEL_SOURCE=minio`, the service downloads the immutable prefix
`ddu-models/ddu-vision/grounded-sam-2/0.4.0/` into the same cache. The prefix
must contain:

- `grounding-dino/` in Hugging Face local-model format
- `sam2_checkpoint.pt`

MinIO uses `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, and `MINIO_SECRET_KEY`.
`MODEL_CACHE_DIR`, `GROUNDING_MODEL_ID`, `SAM2_MODEL_ID`, `BOX_THRESHOLD`, and
`TEXT_THRESHOLD` can override their defaults. `SAM2_MODEL_CONFIG` selects the
config bundled by the pinned SAM 2 package for MinIO checkpoints.

`MODEL_MODE=stub` is only for local contract smoke tests. Its output provenance
is marked `development-stub`.

Other environment variables are `PORT` (8101), `DDU_STORAGE_URL` (8003),
`OPENLINEAGE_URL`, `OPENLINEAGE_NAMESPACE`, and the standard `DDU_*` version
overrides.
