# ddu-ocr

PaddleOCR PP-OCRv4 text extraction service. Implements:
- `GET /healthz`
- `GET /versionz`
- `POST /v1/ocr`

## Run

```bash
pip install -e ../../libs/ddu-py-common
pip install -e '.[model]'
python app.py
```

PaddleOCR downloads its pinned PP-OCRv4 assets on first inference. The service
sets `PADDLE_HOME` to `~/.cache/ddu/models/paddleocr/`; set `MODEL_CACHE_DIR` to
override it. `OCR_LANGUAGE` defaults to `en`.

Paddle's CUDA build is used when available. Otherwise the service logs a warning
and runs on CPU.

`MODEL_MODE=stub` is only for local contract smoke tests. Its output provenance
is marked `development-stub`.

Other environment variables are `PORT` (8103), `DDU_STORAGE_URL` (8003),
`OPENLINEAGE_URL`, `OPENLINEAGE_NAMESPACE`, and the standard `DDU_*` version
overrides.
