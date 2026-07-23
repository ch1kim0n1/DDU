"""LangGraph scripted image workflow orchestration service."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import os
from typing import Any, Awaitable, Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-agent")

VERSION = from_env(ServiceVersion(
    service="ddu-agent",
    service_version="0.0.1-dev",
    tool="langgraph",
    tool_version="0.2.0",
))

VISION_URL = os.environ.get("DDU_VISION_URL", "http://localhost:8101").rstrip("/")
OCR_URL = os.environ.get("DDU_OCR_URL", "http://localhost:8103").rstrip("/")
GEO_URL = os.environ.get("DDU_GEO_URL", "http://localhost:8105").rstrip("/")
ONTOLOGY_URL = os.environ.get("DDU_ONTOLOGY_URL", "http://localhost:8107").rstrip("/")
vision_client = httpx.AsyncClient(base_url=VISION_URL, timeout=60.0)
ocr_client = httpx.AsyncClient(base_url=OCR_URL, timeout=60.0)
geo_client = httpx.AsyncClient(base_url=GEO_URL, timeout=60.0)
ontology_client = httpx.AsyncClient(base_url=ONTOLOGY_URL, timeout=60.0)


class ValueOfInformationEngine:
    """Value of Information (VoI) engine for action prioritization."""
    
    def __init__(self):
        self.action_history: dict[str, list[dict]] = {}
    
    def calculate_voi(
        self,
        action: str,
        current_uncertainty: float,
        expected_information_gain: float,
        cost: float = 1.0,
        action_success_probability: float = 0.8,
    ) -> dict:
        """Calculate Value of Information for an action.
        
        Args:
            action: Action identifier
            current_uncertainty: Current uncertainty level (0-1)
            expected_information_gain: Expected reduction in uncertainty (0-1)
            cost: Cost of performing the action (arbitrary units)
            action_success_probability: Probability of successful execution (0-1)
            
        Returns:
            VoI metrics including expected value, cost-benefit ratio, and priority score
        """
        # Expected Information Gain (EIG)
        eig = expected_information_gain * action_success_probability
        
        # Expected Value = Information Gain - Cost
        expected_value = eig - (cost * 0.1)  # Normalize cost impact
        
        # Priority Score combines uncertainty, information gain, and cost
        priority_score = (
            (current_uncertainty * 0.4) +  # Higher uncertainty = higher priority
            (eig * 0.4) +                    # Higher information gain = higher priority
            ((1.0 / (cost + 0.1)) * 0.2)    # Lower cost = higher priority
        )
        
        # Risk adjustment based on success probability
        risk_adjusted_score = priority_score * action_success_probability
        
        return {
            "action": action,
            "current_uncertainty": current_uncertainty,
            "expected_information_gain": expected_information_gain,
            "expected_value": max(0.0, expected_value),
            "priority_score": max(0.0, min(1.0, priority_score)),
            "risk_adjusted_score": max(0.0, min(1.0, risk_adjusted_score)),
            "cost": cost,
            "action_success_probability": action_success_probability,
            "recommendation": self._get_recommendation(risk_adjusted_score),
        }
    
    def _get_recommendation(self, score: float) -> str:
        """Get action recommendation based on score."""
        if score >= 0.7:
            return "HIGH_PRIORITY"
        elif score >= 0.4:
            return "MEDIUM_PRIORITY"
        elif score >= 0.2:
            return "LOW_PRIORITY"
        else:
            return "SKIP"
    
    def rank_actions(
        self,
        investigation_state: dict,
        available_actions: list[dict],
    ) -> list[dict]:
        """Rank available actions by their Value of Information.
        
        Args:
            investigation_state: Current investigation state
            available_actions: List of available actions with metadata
            
        Returns:
            Ranked list of actions with VoI metrics
        """
        current_uncertainty = investigation_state.get("uncertainty", 0.5)
        
        ranked_actions = []
        for action in available_actions:
            action_id = action.get("id", "unknown")
            expected_gain = action.get("expected_information_gain", 0.5)
            cost = action.get("cost", 1.0)
            success_prob = action.get("success_probability", 0.8)
            
            voi_metrics = self.calculate_voi(
                action=action_id,
                current_uncertainty=current_uncertainty,
                expected_information_gain=expected_gain,
                cost=cost,
                action_success_probability=success_prob,
            )
            
            ranked_actions.append(voi_metrics)
        
        # Sort by risk-adjusted score descending
        ranked_actions.sort(key=lambda x: x["risk_adjusted_score"], reverse=True)
        
        # Record history
        investigation_id = investigation_state.get("investigation_id", "unknown")
        if investigation_id not in self.action_history:
            self.action_history[investigation_id] = []
        self.action_history[investigation_id].append({
            "timestamp": field(default_factory=lambda: None),  # Would need real timestamp
            "ranked_actions": ranked_actions,
        })
        
        return ranked_actions
    
    def get_next_best_action(
        self,
        investigation_state: dict,
        available_actions: list[dict],
        min_score_threshold: float = 0.3,
    ) -> dict:
        """Get the next best action to perform.
        
        Args:
            investigation_state: Current investigation state
            available_actions: List of available actions
            min_score_threshold: Minimum priority score to recommend action
            
        Returns:
            Best action recommendation or skip recommendation
        """
        ranked = self.rank_actions(investigation_state, available_actions)
        
        if not ranked:
            return {
                "recommendation": "NO_ACTIONS_AVAILABLE",
                "action": None,
                "reason": "No actions available to evaluate",
            }
        
        best_action = ranked[0]
        if best_action["risk_adjusted_score"] >= min_score_threshold:
            return {
                "recommendation": best_action["recommendation"],
                "action": best_action["action"],
                "confidence": best_action["risk_adjusted_score"],
                "reason": f"Highest priority action with score {best_action['risk_adjusted_score']:.2f}",
            }
        else:
            return {
                "recommendation": "SKIP",
                "action": None,
                "confidence": best_action["risk_adjusted_score"],
                "reason": f"No actions meet minimum threshold {min_score_threshold}",
            }


# Global VoI engine instance
voi_engine = ValueOfInformationEngine()


class StrategyLearner:
    """Strategy learner for adapting investigation approaches based on performance."""
    
    def __init__(self):
        self.strategy_performance: dict[str, dict] = {}
        self.investigation_outcomes: dict[str, list[dict]] = {}
    
    def record_strategy_execution(
        self,
        strategy_id: str,
        investigation_type: str,
        execution_time: float,
        success: bool,
        information_gain: float,
        cost: float,
    ) -> dict:
        """Record the execution of a strategy and its outcome."""
        if strategy_id not in self.strategy_performance:
            self.strategy_performance[strategy_id] = {
                "total_executions": 0,
                "successful_executions": 0,
                "total_time": 0.0,
                "total_information_gain": 0.0,
                "total_cost": 0.0,
                "investigation_types": {},
            }
        
        perf = self.strategy_performance[strategy_id]
        perf["total_executions"] += 1
        if success:
            perf["successful_executions"] += 1
        perf["total_time"] += execution_time
        perf["total_information_gain"] += information_gain
        perf["total_cost"] += cost
        
        # Track by investigation type
        if investigation_type not in perf["investigation_types"]:
            perf["investigation_types"][investigation_type] = {
                "count": 0,
                "successes": 0,
                "avg_info_gain": 0.0,
            }
        
        type_perf = perf["investigation_types"][investigation_type]
        type_perf["count"] += 1
        if success:
            type_perf["successes"] += 1
        
        # Update average info gain
        type_perf["avg_info_gain"] = (
            (type_perf["avg_info_gain"] * (type_perf["count"] - 1) + information_gain) / 
            type_perf["count"]
        )
        
        return {
            "strategy_id": strategy_id,
            "recorded": True,
            "updated_performance": perf,
        }
    
    def get_strategy_recommendation(
        self,
        investigation_type: str,
        available_strategies: list[str],
    ) -> dict:
        """Get strategy recommendation based on historical performance."""
        if not available_strategies:
            return {
                "recommendation": "NO_STRATEGIES_AVAILABLE",
                "strategy": None,
                "reason": "No strategies provided",
            }
        
        strategy_scores = []
        for strategy_id in available_strategies:
            if strategy_id not in self.strategy_performance:
                # No history - give neutral score
                score = 0.5
                confidence = 0.0
            else:
                perf = self.strategy_performance[strategy_id]
                
                # Calculate success rate
                success_rate = (
                    perf["successful_executions"] / perf["total_executions"]
                    if perf["total_executions"] > 0 else 0.5
                )
                
                # Calculate efficiency (info gain per unit time)
                avg_time = perf["total_time"] / perf["total_executions"]
                avg_info_gain = perf["total_information_gain"] / perf["total_executions"]
                efficiency = avg_info_gain / (avg_time + 1.0)
                
                # Get type-specific performance if available
                type_specific = perf["investigation_types"].get(investigation_type, {})
                type_boost = type_specific.get("avg_info_gain", 0.0) if type_specific else 0.0
                
                # Combined score
                score = (
                    (success_rate * 0.4) +
                    (min(1.0, efficiency) * 0.3) +
                    (min(1.0, type_boost) * 0.3)
                )
                
                # Confidence based on sample size
                confidence = min(1.0, perf["total_executions"] / 10.0)
            
            strategy_scores.append({
                "strategy_id": strategy_id,
                "score": score,
                "confidence": confidence,
            })
        
        # Sort by score descending, then by confidence
        strategy_scores.sort(key=lambda x: (x["score"], x["confidence"]), reverse=True)
        
        best = strategy_scores[0]
        
        if best["score"] >= 0.6 and best["confidence"] >= 0.3:
            recommendation = "RECOMMENDED"
        elif best["score"] >= 0.4:
            recommendation = "ACCEPTABLE"
        else:
            recommendation = "EXPERIMENTAL"
        
        return {
            "recommendation": recommendation,
            "strategy": best["strategy_id"],
            "confidence": best["confidence"],
            "score": best["score"],
            "all_scores": strategy_scores,
            "reason": f"Strategy selected based on {len(strategy_scores)} candidates",
        }
    
    def get_performance_report(self, strategy_id: str) -> dict:
        """Get performance report for a specific strategy."""
        if strategy_id not in self.strategy_performance:
            return {
                "strategy_id": strategy_id,
                "found": False,
                "message": "No performance data available for this strategy",
            }
        
        perf = self.strategy_performance[strategy_id]
        
        return {
            "strategy_id": strategy_id,
            "found": True,
            "performance": {
                "total_executions": perf["total_executions"],
                "success_rate": perf["successful_executions"] / perf["total_executions"],
                "average_time": perf["total_time"] / perf["total_executions"],
                "average_info_gain": perf["total_information_gain"] / perf["total_executions"],
                "average_cost": perf["total_cost"] / perf["total_executions"],
                "efficiency": (
                    perf["total_information_gain"] / (perf["total_time"] + 1.0)
                ),
            },
            "by_investigation_type": perf["investigation_types"],
        }


# Global strategy learner instance
strategy_learner = StrategyLearner()


class InterviewEngine:
    """Interview engine for generating investigation questions and interview plans."""
    
    def __init__(self):
        self.question_templates = {
            "IDENTITY_GAPS": [
                "What is the real identity of the subject identified as {entity}?",
                "Can you confirm if {entity} has used any aliases?",
                "What documents can verify the identity of {entity}?",
            ],
            "TEMPORAL_GAPS": [
                "What was the subject doing between {time1} and {time2}?",
                "Can you account for the subject's whereabouts on {date}?",
                "Who can verify the subject's location at {time}?",
            ],
            "SPATIAL_GAPS": [
                "Why was the subject at {location} on {date}?",
                "How did the subject travel from {location1} to {location2}?",
                "Who else was present at {location} during the incident?",
            ],
            "RELATIONSHIP_GAPS": [
                "What is the nature of the relationship between {entity1} and {entity2}?",
                "How long have {entity1} and {entity2} known each other?",
                "What communications have occurred between {entity1} and {entity2}?",
            ],
            "MOTIVE_GAPS": [
                "What would motivate the subject to engage in this activity?",
                "Who benefits from this outcome?",
                "Are there any financial or personal incentives involved?",
            ],
        }
    
    def identify_gaps(
        self,
        investigation_state: dict,
        entities: list[dict],
        evidence: list[dict],
    ) -> list[dict]:
        """Identify information gaps in the investigation."""
        gaps = []
        
        # Check for identity gaps
        for entity in entities:
            attrs = entity.get("attributes", {}) or {}
            if not attrs.get("name") and not attrs.get("username"):
                gaps.append({
                    "type": "IDENTITY_GAPS",
                    "severity": "HIGH",
                    "entity_id": entity.get("id"),
                    "description": f"Identity information missing for entity {entity.get('id')}",
                })
        
        # Check for temporal gaps
        timestamps = []
        for ev in evidence:
            attrs = ev.get("attributes", {}) or {}
            ts = attrs.get("timestamp", attrs.get("observed_at", ""))
            if ts:
                timestamps.append(ts)
        
        if timestamps:
            timestamps.sort()
            # Look for large time gaps
            for i in range(len(timestamps) - 1):
                # Simplified gap detection
                pass
        
        # Check for spatial gaps
        for ev in evidence:
            attrs = ev.get("attributes", {}) or {}
            if not attrs.get("location") and not attrs.get("latitude"):
                gaps.append({
                    "type": "SPATIAL_GAPS",
                    "severity": "MEDIUM",
                    "evidence_id": ev.get("id"),
                    "description": f"Location information missing for evidence {ev.get('id')}",
                })
        
        return gaps
    
    def generate_questions(
        self,
        gaps: list[dict],
        investigation_context: dict,
        max_questions: int = 10,
    ) -> list[dict]:
        """Generate interview questions based on identified gaps."""
        questions = []
        
        for gap in gaps[:max_questions]:
            gap_type = gap.get("type", "GENERAL")
            templates = self.question_templates.get(gap_type, ["What information can clarify {description}?"])
            
            # Use first matching template
            template = templates[0]
            
            # Fill in template with context
            question_text = template.format(
                entity=gap.get("entity_id", "the subject"),
                entity1=gap.get("entity1_id", "entity A"),
                entity2=gap.get("entity2_id", "entity B"),
                location=gap.get("location", "the location"),
                location1=gap.get("location1", "location A"),
                location2=gap.get("location2", "location B"),
                time=gap.get("time", "the time"),
                time1=gap.get("time1", "time A"),
                time2=gap.get("time2", "time B"),
                date=gap.get("date", "the date"),
                description=gap.get("description", "this aspect"),
            )
            
            questions.append({
                "id": str(uuid4()),
                "question": question_text,
                "gap_type": gap_type,
                "severity": gap.get("severity", "MEDIUM"),
                "target_entity": gap.get("entity_id"),
                "target_evidence": gap.get("evidence_id"),
                "priority": self._calculate_priority(gap),
            })
        
        # Sort by priority
        questions.sort(key=lambda x: x["priority"], reverse=True)
        
        return questions
    
    def _calculate_priority(self, gap: dict) -> float:
        """Calculate priority score for a gap."""
        severity_scores = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}
        base_score = severity_scores.get(gap.get("severity", "MEDIUM"), 0.5)
        
        # Boost priority if it affects multiple entities/evidence
        multiplier = 1.0
        if gap.get("entity_id") and gap.get("evidence_id"):
            multiplier = 1.2
        
        return base_score * multiplier
    
    def create_interview_plan(
        self,
        investigation_state: dict,
        entities: list[dict],
        evidence: list[dict],
        interview_duration_minutes: int = 60,
    ) -> dict:
        """Create a structured interview plan."""
        gaps = self.identify_gaps(investigation_state, entities, evidence)
        questions = self.generate_questions(gaps, investigation_state)
        
        # Allocate time per question
        time_per_question = interview_duration_minutes / max(1, len(questions))
        
        # Group questions by type
        grouped = {}
        for q in questions:
            gap_type = q["gap_type"]
            if gap_type not in grouped:
                grouped[gap_type] = []
            grouped[gap_type].append(q)
        
        return {
            "investigation_id": investigation_state.get("investigation_id", "unknown"),
            "total_duration_minutes": interview_duration_minutes,
            "total_questions": len(questions),
            "identified_gaps": len(gaps),
            "questions": questions,
            "question_groups": [
                {
                    "type": gap_type,
                    "questions": group_questions,
                    "count": len(group_questions),
                    "estimated_minutes": len(group_questions) * time_per_question,
                }
                for gap_type, group_questions in grouped.items()
            ],
            "high_priority_questions": [q for q in questions if q["priority"] >= 0.7],
            "recommended_approach": self._get_approach_recommendation(gaps),
        }
    
    def _get_approach_recommendation(self, gaps: list[dict]) -> str:
        """Get recommendation for interview approach based on gaps."""
        high_severity = sum(1 for g in gaps if g.get("severity") == "HIGH")
        
        if high_severity >= 3:
            return "COMPREHENSIVE: Multiple high-priority gaps require detailed examination"
        elif high_severity >= 1:
            return "FOCUSED: Address high-priority gaps first, then cover remaining areas"
        else:
            return "STANDARD: Cover all identified gaps systematically"


# Global interview engine instance
interview_engine = InterviewEngine()


class WorkflowImageRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    prompts: list[str] = Field(default_factory=list)


class VOIAction(BaseModel):
    id: str = Field(min_length=1)
    expected_information_gain: float = Field(default=0.5, ge=0.0, le=1.0)
    cost: float = Field(default=1.0, ge=0.0)
    success_probability: float = Field(default=0.8, ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)


class VOIRequest(BaseModel):
    investigation_state: dict = Field(default_factory=dict)
    available_actions: list[VOIAction] = Field(default_factory=list)
    min_score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class StrategyExecutionRecord(BaseModel):
    strategy_id: str = Field(min_length=1)
    investigation_type: str = Field(min_length=1)
    execution_time: float = Field(ge=0.0)
    success: bool
    information_gain: float = Field(ge=0.0, le=1.0)
    cost: float = Field(ge=0.0)


class StrategyRecommendationRequest(BaseModel):
    investigation_type: str = Field(min_length=1)
    available_strategies: list[str] = Field(default_factory=list)


class InterviewPlanRequest(BaseModel):
    investigation_state: dict = Field(default_factory=dict)
    entities: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    interview_duration_minutes: int = Field(default=60, ge=1, le=480)


class InterviewQuestionsRequest(BaseModel):
    investigation_state: dict = Field(default_factory=dict)
    gaps: list[dict] = Field(default_factory=list)
    max_questions: int = Field(default=10, ge=1, le=50)


@dataclass
class StepResult:
    step: str
    status: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)


class WorkflowAdapter(Protocol):
    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]: ...


class DirectWorkflowAdapter:
    def __init__(self) -> None:
        self._vision = vision_client
        self._ocr = ocr_client
        self._geo = geo_client
        self._ontology = ontology_client

    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]:
        observations: list[dict[str, Any]] = []
        entities: list[dict[str, Any]] = []
        steps: list[StepResult] = []

        detect_payload: dict[str, Any] = {
            "evidence_id": evidence_id,
            "investigation_id": investigation_id,
        }
        if prompts:
            detect_payload["prompts"] = prompts
        vision_obs = await self._call_step(
            "ddu-vision:detect",
            self._vision.post("/v1/detect", json=detect_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(vision_obs)
        steps.append(StepResult("ddu-vision:detect", "COMPLETE", vision_obs))

        ocr_payload = {"evidence_id": evidence_id, "investigation_id": investigation_id}
        ocr_obs = await self._call_step(
            "ddu-ocr:extract",
            self._ocr.post("/v1/ocr", json=ocr_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(ocr_obs)
        steps.append(StepResult("ddu-ocr:extract", "COMPLETE", ocr_obs))

        geo_payload = {"evidence_id": evidence_id, "investigation_id": investigation_id}
        geo_obs = await self._call_step(
            "ddu-geo:locate",
            self._geo.post("/v1/locate", json=geo_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(geo_obs)
        steps.append(StepResult("ddu-geo:locate", "COMPLETE", geo_obs))

        created_entities = await self._create_entities(
            observations, investigation_id, evidence_id, run_id,
        )
        entities.extend(created_entities)
        steps.append(StepResult("ddu-ontology:create-entities", "COMPLETE", [], created_entities))
        return observations, entities, steps

    async def _call_step(
        self,
        job_name: str,
        call: Awaitable[httpx.Response],
        run_id: str,
        investigation_id: str,
        evidence_id: str,
    ) -> list[dict[str, Any]]:
        facets = {"dduInvestigation": {"investigation_id": investigation_id}}
        lineage.emit(Event(
            event_type="START",
            run_id=run_id,
            job_name=job_name,
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            facets=facets,
        ))
        try:
            response = await call
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            lineage.emit(Event(
                event_type="FAIL",
                run_id=run_id,
                job_name=job_name,
                facets=facets,
            ))
            raise RuntimeError(f"{job_name} failed: {exc}") from exc
        lineage.emit(Event(
            event_type="COMPLETE",
            run_id=run_id,
            job_name=job_name,
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            outputs=[
                Output(
                    namespace=investigation_id,
                    name=item.get("id", str(uuid4())),
                    type="DDU.OBSERVATION",
                )
                for item in result
            ],
            facets=facets,
        ))
        return result

    async def _create_entities(
        self,
        observations: list[dict[str, Any]],
        investigation_id: str,
        evidence_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        facets = {"dduInvestigation": {"investigation_id": investigation_id}}
        lineage.emit(Event(
            event_type="START",
            run_id=run_id,
            job_name="ddu-ontology:create-entities",
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            facets=facets,
        ))
        entities: list[dict[str, Any]] = []
        for observation in observations:
            entity = {
                "investigation_id": investigation_id,
                "type": "ENTITY_TYPE_OBSERVATION",
                "attributes": {
                    "label": str(observation.get("label", "")),
                    "observation_type": str(observation.get("type", "")),
                },
                "evidence_ids": [evidence_id],
                "provenance": {
                    "produced_by_service": VERSION.service,
                    "run_id": run_id,
                    "job_name": "ddu-agent:workflow-image",
                },
            }
            try:
                response = await self._ontology.post("/v1/entities", json=entity)
                response.raise_for_status()
                entities.append(response.json())
            except httpx.HTTPError as exc:
                log.warning("ontology entity creation failed: %s", exc)
        lineage.emit(Event(
            event_type="COMPLETE",
            run_id=run_id,
            job_name="ddu-ontology:create-entities",
            outputs=[
                Output(
                    namespace=investigation_id,
                    name=entity.get("id", str(uuid4())),
                    type="DDU.ENTITY",
                )
                for entity in entities
            ],
            facets=facets,
        ))
        return entities


class LangGraphWorkflowAdapter:
    """LangGraph state machine: vision → ocr → geo → ontology."""

    def __init__(self) -> None:
        self._direct = DirectWorkflowAdapter()
        self._graph = None

    def _build_graph(self) -> Any:
        from typing import Annotated, TypedDict
        import operator

        from langgraph.graph import END, START, StateGraph

        class WorkflowState(TypedDict):
            evidence_id: str
            investigation_id: str
            prompts: list[str]
            run_id: str
            observations: Annotated[list[dict[str, Any]], operator.add]
            entities: Annotated[list[dict[str, Any]], operator.add]
            steps: Annotated[list[dict[str, Any]], operator.add]

        async def vision_node(state: WorkflowState) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "evidence_id": state["evidence_id"],
                "investigation_id": state["investigation_id"],
            }
            if state.get("prompts"):
                payload["prompts"] = state["prompts"]
            obs = await self._direct._call_step(
                "ddu-vision:detect",
                self._direct._vision.post("/v1/detect", json=payload),
                state["run_id"],
                state["investigation_id"],
                state["evidence_id"],
            )
            return {
                "observations": obs,
                "steps": [{"step": "ddu-vision:detect", "status": "COMPLETE", "observations": obs, "entities": []}],
            }

        async def ocr_node(state: WorkflowState) -> dict[str, Any]:
            payload = {
                "evidence_id": state["evidence_id"],
                "investigation_id": state["investigation_id"],
            }
            obs = await self._direct._call_step(
                "ddu-ocr:extract",
                self._direct._ocr.post("/v1/ocr", json=payload),
                state["run_id"],
                state["investigation_id"],
                state["evidence_id"],
            )
            return {
                "observations": obs,
                "steps": [{"step": "ddu-ocr:extract", "status": "COMPLETE", "observations": obs, "entities": []}],
            }

        async def geo_node(state: WorkflowState) -> dict[str, Any]:
            payload = {
                "evidence_id": state["evidence_id"],
                "investigation_id": state["investigation_id"],
            }
            obs = await self._direct._call_step(
                "ddu-geo:locate",
                self._direct._geo.post("/v1/locate", json=payload),
                state["run_id"],
                state["investigation_id"],
                state["evidence_id"],
            )
            return {
                "observations": obs,
                "steps": [{"step": "ddu-geo:locate", "status": "COMPLETE", "observations": obs, "entities": []}],
            }

        async def ontology_node(state: WorkflowState) -> dict[str, Any]:
            entities = await self._direct._create_entities(
                state.get("observations", []),
                state["investigation_id"],
                state["evidence_id"],
                state["run_id"],
            )
            return {
                "entities": entities,
                "steps": [{
                    "step": "ddu-ontology:create-entities",
                    "status": "COMPLETE",
                    "observations": [],
                    "entities": entities,
                }],
            }

        builder = StateGraph(WorkflowState)
        builder.add_node("vision", vision_node)
        builder.add_node("ocr", ocr_node)
        builder.add_node("geo", geo_node)
        builder.add_node("ontology", ontology_node)
        builder.add_edge(START, "vision")
        builder.add_edge("vision", "ocr")
        builder.add_edge("ocr", "geo")
        builder.add_edge("geo", "ontology")
        builder.add_edge("ontology", END)
        return builder.compile()

    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]:
        try:
            if self._graph is None:
                self._graph = self._build_graph()
        except ImportError:
            log.warning("langgraph not installed; falling back to direct orchestration")
            return await self._direct.run_image_workflow(
                evidence_id, investigation_id, prompts, run_id,
            )

        result = await self._graph.ainvoke({
            "evidence_id": evidence_id,
            "investigation_id": investigation_id,
            "prompts": prompts,
            "run_id": run_id,
            "observations": [],
            "entities": [],
            "steps": [],
        })
        steps = [
            StepResult(
                step=item.get("step", "unknown"),
                status=item.get("status", "COMPLETE"),
                observations=item.get("observations", []) or [],
                entities=item.get("entities", []) or [],
            )
            for item in result.get("steps", [])
        ]
        return result.get("observations", []), result.get("entities", []), steps


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
# Prefer LangGraph whenever importable; stub mode still uses the graph with stub ML deps.
try:
    import langgraph  # noqa: F401

    workflow_adapter: WorkflowAdapter = LangGraphWorkflowAdapter()
except ImportError:
    workflow_adapter = DirectWorkflowAdapter()


class AutonomousRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    evidence_id: str | None = None
    query: str | None = None
    template: str | None = None
    prompts: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    launched_by_role: str = "investigator"


class TemplateRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    template: str = Field(min_length=1)
    evidence_id: str | None = None
    prompts: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    launched_by_role: str = "investigator"


class QueryRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    launched_by_role: str = "investigator"


TEMPLATES = {
    "image-triage": ["person", "vehicle", "weapon", "text"],
    "username-hunt": ["account", "email", "phone"],
    "location-focus": ["landmark", "signage", "vehicle"],
}


@app.post("/v1/workflow/autonomous")
async def workflow_autonomous(request: AutonomousRequest) -> dict:
    """Phase 3 autonomous workflow: plan steps from goal, then execute scripted chain."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:workflow-autonomous",
        facets=facets,
    ))
    plan = [
        {"step": "ingest_or_select_evidence", "status": "PLANNED"},
        {"step": "run_perception", "status": "PLANNED"},
        {"step": "persist_observations", "status": "PLANNED"},
        {"step": "propose_candidates", "status": "PLANNED"},
    ]
    result: dict[str, Any] = {
        "mode": "autonomous",
        "plan": plan,
        "launched_by_role": request.launched_by_role,
        "query": request.query,
    }
    if request.evidence_id:
        try:
            observations, entities, steps = await workflow_adapter.run_image_workflow(
                request.evidence_id,
                request.investigation_id,
                request.prompts or TEMPLATES["image-triage"],
                run_id,
            )
            result.update({
                "evidence_id": request.evidence_id,
                "observations": observations,
                "entities": entities,
                "steps": [
                    {
                        "step": step.step,
                        "status": step.status,
                        "observations": step.observations,
                        "entities": step.entities,
                    }
                    for step in steps
                ],
            })
            for item in plan:
                item["status"] = "COMPLETE"
        except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
            lineage.emit(Event(
                event_type="FAIL",
                run_id=run_id,
                job_name="ddu-agent:workflow-autonomous",
                facets=facets,
            ))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        result["note"] = "No evidence_id provided; returned plan only."
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:workflow-autonomous",
        facets=facets,
    ))
    return result


@app.post("/v1/workflow/template")
async def workflow_template(request: TemplateRequest) -> dict:
    prompts = TEMPLATES.get(request.template, request.prompts)
    if request.evidence_id:
        image_request = WorkflowImageRequest(
            evidence_id=request.evidence_id,
            investigation_id=request.investigation_id,
            prompts=prompts,
        )
        body = await workflow_image(image_request)
        body["template"] = request.template
        body["launched_by_role"] = request.launched_by_role
        return body
    return {
        "template": request.template,
        "prompts": prompts,
        "investigation_id": request.investigation_id,
        "status": "READY",
        "launched_by_role": request.launched_by_role,
    }


@app.post("/v1/query")
async def natural_language_query(request: QueryRequest) -> dict:
    """NL investigation query — maps keywords to planned service calls (no LLM required)."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:nl-query",
        facets=facets,
    ))
    query = request.query.lower()
    actions: list[dict[str, str]] = []
    if any(token in query for token in ("username", "account", "sherlock")):
        actions.append({"service": "ddu-discovery", "action": "discover"})
    if any(token in query for token in ("osint", "enrich", "spiderfoot")):
        actions.append({"service": "ddu-osint", "action": "enrich"})
    if any(token in query for token in ("face", "person", "identity")):
        actions.append({"service": "ddu-face", "action": "match"})
    if any(token in query for token in ("audio", "transcribe", "speech")):
        actions.append({"service": "ddu-audio", "action": "transcribe"})
    if any(token in query for token in ("where", "location", "geo", "map")):
        actions.append({"service": "ddu-geo", "action": "locate"})
    if any(token in query for token in ("resolve", "same", "link")):
        actions.append({"service": "ddu-resolution", "action": "resolve"})
    if not actions:
        actions.append({"service": "ddu-agent", "action": "workflow-image"})
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:nl-query",
        facets=facets,
    ))
    return {
        "investigation_id": request.investigation_id,
        "query": request.query,
        "planned_actions": actions,
        "launched_by_role": request.launched_by_role,
        "epistemic_note": "Planned actions are suggestions; outputs remain observations/candidates.",
    }


@app.post("/v1/workflow/image")
async def workflow_image(request: WorkflowImageRequest) -> dict:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:workflow-image",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
        facets=facets,
    ))
    try:
        observations, entities, steps = await workflow_adapter.run_image_workflow(
            request.evidence_id,
            request.investigation_id,
            request.prompts,
            run_id,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-agent:workflow-image",
            facets=facets,
        ))
        log.exception("image workflow failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:workflow-image",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item.get("id", str(uuid4())),
                type="DDU.OBSERVATION",
            )
            for item in observations
        ]
        + [
            Output(
                namespace=request.investigation_id,
                name=item.get("id", str(uuid4())),
                type="DDU.ENTITY",
            )
            for item in entities
        ],
        facets=facets,
    ))
    return {
        "evidence_id": request.evidence_id,
        "observations": observations,
        "entities": entities,
        "steps": [
            {
                "step": step.step,
                "status": step.status,
                "observations": step.observations,
                "entities": step.entities,
            }
            for step in steps
        ],
    }


@app.post("/v1/voi/rank")
async def rank_actions_voi(request: VOIRequest) -> dict:
    """Rank actions by Value of Information."""
    run_id = lineage.new_run_id()
    investigation_id = request.investigation_state.get("investigation_id", "unknown")
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:voi-rank",
        inputs=[Input(
            namespace=investigation_id,
            name=investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    
    actions_dict = [action.dict() for action in request.available_actions]
    ranked_actions = voi_engine.rank_actions(
        investigation_state=request.investigation_state,
        available_actions=actions_dict,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:voi-rank",
        outputs=[Output(
            namespace=investigation_id,
            name=investigation_id,
            type="DDU.VOI_RANKING",
        )],
        facets=facets,
    ))
    
    return {
        "investigation_id": investigation_id,
        "ranked_actions": ranked_actions,
        "total_actions": len(ranked_actions),
    }


@app.post("/v1/voi/next-action")
async def get_next_action_voi(request: VOIRequest) -> dict:
    """Get the next best action using Value of Information."""
    run_id = lineage.new_run_id()
    investigation_id = request.investigation_state.get("investigation_id", "unknown")
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:voi-next-action",
        inputs=[Input(
            namespace=investigation_id,
            name=investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    
    actions_dict = [action.dict() for action in request.available_actions]
    recommendation = voi_engine.get_next_best_action(
        investigation_state=request.investigation_state,
        available_actions=actions_dict,
        min_score_threshold=request.min_score_threshold,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:voi-next-action",
        outputs=[Output(
            namespace=investigation_id,
            name=recommendation.get("action", "none"),
            type="DDU.VOI_RECOMMENDATION",
        )],
        facets=facets,
    ))
    
    return {
        "investigation_id": investigation_id,
        "recommendation": recommendation,
        "threshold_used": request.min_score_threshold,
    }


@app.post("/v1/voi/calculate")
async def calculate_single_voi(
    action: str,
    current_uncertainty: float = 0.5,
    expected_information_gain: float = 0.5,
    cost: float = 1.0,
    action_success_probability: float = 0.8,
) -> dict:
    """Calculate VoI for a single action."""
    voi_metrics = voi_engine.calculate_voi(
        action=action,
        current_uncertainty=current_uncertainty,
        expected_information_gain=expected_information_gain,
        cost=cost,
        action_success_probability=action_success_probability,
    )
    
    return voi_metrics


@app.post("/v1/strategy/record")
async def record_strategy(request: StrategyExecutionRecord) -> dict:
    """Record strategy execution outcome for learning."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"strategy_id": request.strategy_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:strategy-record",
        inputs=[Input(
            namespace=request.strategy_id,
            name=request.strategy_id,
            type="DDU.STRATEGY",
        )],
        facets=facets,
    ))
    
    result = strategy_learner.record_strategy_execution(
        strategy_id=request.strategy_id,
        investigation_type=request.investigation_type,
        execution_time=request.execution_time,
        success=request.success,
        information_gain=request.information_gain,
        cost=request.cost,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:strategy-record",
        outputs=[Output(
            namespace=request.strategy_id,
            name=request.strategy_id,
            type="DDU.STRATEGY_PERFORMANCE",
        )],
        facets=facets,
    ))
    
    return result


@app.post("/v1/strategy/recommend")
async def recommend_strategy(request: StrategyRecommendationRequest) -> dict:
    """Get strategy recommendation based on learned performance."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_type": request.investigation_type}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:strategy-recommend",
        inputs=[Input(
            namespace=request.investigation_type,
            name=request.investigation_type,
            type="DDU.INVESTIGATION_TYPE",
        )],
        facets=facets,
    ))
    
    recommendation = strategy_learner.get_strategy_recommendation(
        investigation_type=request.investigation_type,
        available_strategies=request.available_strategies,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:strategy-recommend",
        outputs=[Output(
            namespace=request.investigation_type,
            name=recommendation.get("strategy", "none"),
            type="DDU.STRATEGY_RECOMMENDATION",
        )],
        facets=facets,
    ))
    
    return recommendation


@app.get("/v1/strategy/performance/{strategy_id}")
async def get_strategy_performance(strategy_id: str) -> dict:
    """Get performance report for a specific strategy."""
    report = strategy_learner.get_performance_report(strategy_id)
    return report


@app.post("/v1/interview/plan")
async def create_interview_plan(request: InterviewPlanRequest) -> dict:
    """Create a structured interview plan based on investigation gaps."""
    run_id = lineage.new_run_id()
    investigation_id = request.investigation_state.get("investigation_id", "unknown")
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:interview-plan",
        inputs=[Input(
            namespace=investigation_id,
            name=investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    
    plan = interview_engine.create_interview_plan(
        investigation_state=request.investigation_state,
        entities=request.entities,
        evidence=request.evidence,
        interview_duration_minutes=request.interview_duration_minutes,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:interview-plan",
        outputs=[Output(
            namespace=investigation_id,
            name=f"interview_plan_{investigation_id}",
            type="DDU.INTERVIEW_PLAN",
        )],
        facets=facets,
    ))
    
    return plan


@app.post("/v1/interview/gaps")
async def identify_gaps(request: InterviewPlanRequest) -> dict:
    """Identify information gaps in the investigation."""
    gaps = interview_engine.identify_gaps(
        investigation_state=request.investigation_state,
        entities=request.entities,
        evidence=request.evidence,
    )
    
    return {
        "investigation_id": request.investigation_state.get("investigation_id", "unknown"),
        "gaps": gaps,
        "total_gaps": len(gaps),
    }


@app.post("/v1/interview/questions")
async def generate_questions(request: InterviewQuestionsRequest) -> dict:
    """Generate interview questions based on identified gaps."""
    questions = interview_engine.generate_questions(
        gaps=request.gaps,
        investigation_context=request.investigation_state,
        max_questions=request.max_questions,
    )
    
    return {
        "investigation_id": request.investigation_state.get("investigation_id", "unknown"),
        "questions": questions,
        "total_questions": len(questions),
    }


def main() -> None:
    port = int(os.environ.get("PORT", 8109))
    log.info("ddu-agent listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
