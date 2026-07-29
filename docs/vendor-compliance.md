# Vendor compliance / DPA status

| Vendor | Purpose | Required? | DPA status |
|---|---|---|---|
| Anthropic | Remediation / grounded copy | Optional | Confirm DPA before production LLM use |
| ElevenLabs | STT/TTS | Optional | Confirm DPA before production voice use |
| OpenStreetMap tiles | Map basemap | Browser-side | Public tile usage policy applies |
| Sentry | Error tracking | Optional | Enable PII scrubbing (configured) |
| CompreFace | Face match | Optional | Keep private network only |

Update this table when a vendor is enabled in production.
