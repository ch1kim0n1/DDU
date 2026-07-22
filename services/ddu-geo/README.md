# ddu-geo

GeoCLIP image geolocation service. Implements:
- `GET /healthz`
- `GET /versionz`
- `POST /v1/locate`

## Run

```bash
pip install -e ../../libs/ddu-py-common
pip install -e '.[model]'
python app.py
```

The pinned `geoclip==1.2.0` package loads the official pretrained checkpoint on
first inference. Torch and Hugging Face caches are rooted at
`~/.cache/ddu/models/geoclip/`; set `MODEL_CACHE_DIR` to override this path.

CUDA is selected when `torch.cuda.is_available()`. Otherwise the service logs a
warning and runs on CPU. Location labels use coordinates when the model does not
provide a place name; coordinates and uncertainty remain available in `geo`.

`MODEL_MODE=stub` is only for local contract smoke tests. Its output provenance
is marked `development-stub`.

Other environment variables are `PORT` (8105), `DDU_STORAGE_URL` (8003),
`OPENLINEAGE_URL`, `OPENLINEAGE_NAMESPACE`, and the standard `DDU_*` version
overrides.
