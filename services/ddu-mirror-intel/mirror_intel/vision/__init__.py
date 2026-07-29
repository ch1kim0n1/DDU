"""Engineer C — Vision & Biometrics for DDU Mirror.

Produces schema-valid findings from operator uploads:
EXIF GPS/device, hash-cached object detections (Grounded-SAM-2),
hash-cached GeoCLIP hypotheses, and closed-corpus face linkability.

Heavy models are never required on the demo path — upload hits
``data/vision_cache`` by content hash. Live CompreFace is optional.
"""

from .pipeline import analyze_upload, VisionAnalyzeResult
from .corpus import ClosedCorpus, CorpusViolation
from .liveness import LivenessStore

__all__ = [
    "analyze_upload",
    "VisionAnalyzeResult",
    "ClosedCorpus",
    "CorpusViolation",
    "LivenessStore",
]
