"""Checkpointed LangGraph approval runtime.

Each proposal gets a stable LangGraph thread. Planning arms the thread and
hits a real ``interrupt``. Approve/edit/reject resumes that exact checkpoint
with ``Command(resume=...)``; discovery executes only in the post-interrupt
node.

Raw edits are first written to the encrypted session backend and referenced
from graph state by proposal id. This keeps identity values out of the
LangGraph checkpoint index while preserving cross-worker resume.
"""

from __future__ import annotations

import math
import os
import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import orchestrator as orch
from .guardrails import TargetRefusedError
from .schema import ProposalStatus
from .session import SessionConflictError, store

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


class WorkflowDecisionError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class ApprovalState(TypedDict, total=False):
    session_id: str
    proposal_id: str
    action: str
    status: str
    finding_ids: list[str]
    worker_meta: dict[str, Any]


def _thread_id(session_id: str, proposal_id: str) -> str:
    return f"mirror:{session_id}:{proposal_id}"


def _review(state: ApprovalState) -> dict[str, Any]:
    session = store.require(state["session_id"])
    proposal = session.proposals.get(state["proposal_id"])
    if proposal is None:
        raise WorkflowDecisionError(404, f"unknown proposal {state['proposal_id']}")
    decision = interrupt(
        {
            "event": "agent.awaiting_approval",
            "proposal": proposal.model_dump(mode="json"),
            "allowed": ["approve", "edit", "reject"],
        }
    )
    return {"action": str(dict(decision).get("action", ""))}


def _decide(state: ApprovalState) -> dict[str, Any]:
    session = store.require(state["session_id"])
    proposal_id = state["proposal_id"]
    pending_decisions = dict(session.workflow_state.get("decisions", {}))
    decision = dict(pending_decisions.pop(proposal_id, {}))
    if not decision:
        raise WorkflowDecisionError(409, "no encrypted human decision is pending")
    session.workflow_state["decisions"] = pending_decisions

    orchestrator = orch.for_session(session)
    action = str(decision.get("action", state.get("action", "")))
    try:
        if action == "approve":
            orchestrator.approve(proposal_id)
            added, meta = orchestrator.execute(proposal_id)
            status = ProposalStatus.EXECUTED.value
        elif action == "edit":
            orchestrator.edit_and_approve(
                proposal_id,
                dict(decision.get("changes") or {}),
                decision.get("reason"),
            )
            added, meta = orchestrator.execute(proposal_id)
            status = ProposalStatus.EXECUTED.value
        elif action == "reject":
            orchestrator.reject(proposal_id, decision.get("reason"))
            added, meta = [], {}
            status = ProposalStatus.REJECTED.value
        else:
            raise WorkflowDecisionError(400, f"unsupported decision {action!r}")
    except TargetRefusedError as exc:
        store.persist(session)
        raise WorkflowDecisionError(403, exc.as_payload()) from exc
    except KeyError as exc:
        raise WorkflowDecisionError(404, str(exc)) from exc
    except (PermissionError, ValueError, SessionConflictError) as exc:
        raise WorkflowDecisionError(409, str(exc)) from exc

    store.persist(session)
    return {
        "action": action,
        "status": status,
        "finding_ids": [finding.id for finding in added],
        "worker_meta": {
            key: value
            for key, value in meta.items()
            if isinstance(value, (str, int, float, bool, list, type(None)))
        },
    }


def _checkpointer() -> tuple[Any, str]:
    redis_url = os.environ.get("MIRROR_REDIS_URL", "").strip()
    if redis_url:
        from langgraph.checkpoint.redis import RedisSaver

        ttl_seconds = int(os.environ.get("MIRROR_SESSION_TTL_SECONDS", "1800"))
        saver = RedisSaver(
            redis_url=redis_url,
            ttl={
                "default_ttl": max(1, math.ceil(ttl_seconds / 60)),
                "refresh_on_read": True,
            },
            checkpoint_prefix="ddu_mirror_checkpoint",
            checkpoint_write_prefix="ddu_mirror_checkpoint_write",
        )
        saver.setup()
        return saver, "redis"

    checkpoint_path = os.environ.get("MIRROR_CHECKPOINT_DB", "").strip()
    if checkpoint_path:
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = Path(checkpoint_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, check_same_thread=False)
        return SqliteSaver(connection), "sqlite"
    return InMemorySaver(), "memory"


class ApprovalRuntime:
    def __init__(self) -> None:
        checkpointer, backend = _checkpointer()
        builder = StateGraph(ApprovalState)
        builder.add_node("human_review", _review)
        builder.add_node("execute_decision", _decide)
        builder.add_edge(START, "human_review")
        builder.add_edge("human_review", "execute_decision")
        builder.add_edge("execute_decision", END)
        self.graph = builder.compile(checkpointer=checkpointer)
        self.backend = backend

    def arm(self, session_id: str, proposal_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": _thread_id(session_id, proposal_id)}}
        result = self.graph.invoke(
            {"session_id": session_id, "proposal_id": proposal_id, "status": "pending"},
            config=config,
        )
        interrupts = result.get("__interrupt__", ())
        return {
            "thread_id": _thread_id(session_id, proposal_id),
            "interrupted": bool(interrupts),
            "backend": self.backend,
        }

    def resume(
        self,
        session_id: str,
        proposal_id: str,
        *,
        action: str,
        changes: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        session = store.require(session_id)
        decisions = dict(session.workflow_state.get("decisions", {}))
        decisions[proposal_id] = {
            "action": action,
            "changes": dict(changes or {}),
            "reason": reason,
        }
        session.workflow_state["decisions"] = decisions
        store.persist(session)

        config = {"configurable": {"thread_id": _thread_id(session_id, proposal_id)}}
        result = self.graph.invoke(Command(resume={"action": action}), config=config)
        current = store.require(session_id)
        proposal = current.proposals.get(proposal_id)
        if proposal is None:
            raise WorkflowDecisionError(404, f"unknown proposal {proposal_id}")
        finding_ids = set(result.get("finding_ids", []))
        added = [finding for finding in current.findings if finding.id in finding_ids]
        assert current.score is not None
        return {
            "session_id": session_id,
            "proposal_id": proposal_id,
            "proposal": proposal.model_dump(mode="json"),
            "findings": [finding.model_dump(mode="json") for finding in added],
            "findings_added": len(added),
            "worker_meta": dict(result.get("worker_meta", {})),
            "score": current.score.model_dump(mode="json"),
            "attack_paths": [
                path.model_dump(mode="json") for path in current.attack_paths
            ],
            "attribution": [
                item.model_dump(mode="json") for item in current.attribution
            ],
            "workflow": {
                "runtime": "langgraph",
                "checkpoint_backend": self.backend,
                "thread_id": _thread_id(session_id, proposal_id),
                "resumed": True,
            },
        }

    def status(self) -> dict[str, Any]:
        return {
            "runtime": "langgraph",
            "checkpoint_backend": self.backend,
            "durable": self.backend in {"redis", "sqlite"},
        }


runtime = ApprovalRuntime()
