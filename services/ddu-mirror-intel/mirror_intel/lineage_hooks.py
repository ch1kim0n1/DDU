"""Best-effort OpenLineage emission for Mirror intel invocations."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env

from mirror_intel import __version__
from mirror_intel.schema import CONTRACT_VERSION

log = logging.getLogger("ddu-mirror-intel.lineage")

_emitter: LineageEmitter | None = None


def _get_emitter() -> LineageEmitter:
    global _emitter
    if _emitter is None:
        version = from_env(
            ServiceVersion(
                service="ddu-mirror-intel",
                service_version=__version__,
                tool="ddu-mirror-findings-contract",
                tool_version=CONTRACT_VERSION,
            )
        )
        _emitter = LineageEmitter(version)
    return _emitter


@contextmanager
def lineage_run(
    job_name: str,
    *,
    session_id: str = "",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
) -> Iterator[str]:
    emitter = _get_emitter()
    run_id = emitter.new_run_id()
    in_ds = [
        Input(namespace="ddu.mirror", name=name, type="EVIDENCE")
        for name in (inputs or ([f"session:{session_id}"] if session_id else []))
    ]
    out_ds = [
        Output(namespace="ddu.mirror", name=name, type="EVIDENCE")
        for name in (outputs or [])
    ]
    emitter.emit(
        Event(
            event_type="START",
            run_id=run_id,
            job_name=job_name,
            inputs=in_ds,
            facets={"session_id": session_id} if session_id else {},
        )
    )
    try:
        yield run_id
        emitter.emit(
            Event(
                event_type="COMPLETE",
                run_id=run_id,
                job_name=job_name,
                inputs=in_ds,
                outputs=out_ds,
                facets={"session_id": session_id} if session_id else {},
            )
        )
    except Exception as exc:
        emitter.emit(
            Event(
                event_type="FAIL",
                run_id=run_id,
                job_name=job_name,
                inputs=in_ds,
                facets={"session_id": session_id, "error": str(exc)[:200]},
            )
        )
        raise
