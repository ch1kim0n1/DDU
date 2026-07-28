"""Splink + Qdrant entity resolution candidate relationship service."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
import os
from typing import Any, Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.runtime import model_mode_is_stub
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-resolution")

VERSION = from_env(ServiceVersion(
    service="ddu-resolution",
    service_version="0.0.1-dev",
    tool="splink",
    tool_version="4.0.0",
    model="splink",
    model_version="4.0.0",
))

GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
VECTOR_URL = os.environ.get("DDU_VECTOR_URL", "http://localhost:8005").rstrip("/")
graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=30.0)
vector_client = httpx.AsyncClient(base_url=VECTOR_URL, timeout=30.0)


@dataclass
class ConfidenceHistory:
    prior_confidence: float
    likelihood: float
    posterior_confidence: float
    evidence_id: str
    signal_type: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BeliefEngine:
    """Bayesian belief engine for confidence evolution."""
    
    def __init__(self, prior_confidence: float = 0.5):
        self.prior_confidence = prior_confidence
        self.history: dict[str, list[ConfidenceHistory]] = {}
    
    def update_belief(
        self,
        relationship_id: str,
        current_confidence: float,
        new_signal_strength: float,
        signal_reliability: float = 0.8,
        evidence_id: str = "",
        signal_type: str = "generic",
    ) -> tuple[float, ConfidenceHistory]:
        """Update confidence using Bayesian inference.
        
        Args:
            relationship_id: ID of the relationship
            current_confidence: Current confidence value (0-1)
            new_signal_strength: Strength of new evidence (0-1)
            signal_reliability: Reliability of the signal source (0-1)
            evidence_id: ID of supporting evidence
            signal_type: Type of signal
            
        Returns:
            Tuple of (new_confidence, history_entry)
        """
        # Bayesian update: P(H|E) = P(E|H) * P(H) / P(E)
        # Simplified: posterior = likelihood * prior / normalization
        
        likelihood = signal_reliability * new_signal_strength
        prior = current_confidence
        
        # Normalize to avoid division by zero
        normalization = likelihood * prior + (1 - signal_reliability) * (1 - prior)
        if normalization == 0:
            posterior = prior
        else:
            posterior = (likelihood * prior) / normalization
        
        # Clamp to valid range
        posterior = max(0.0, min(1.0, posterior))
        
        history_entry = ConfidenceHistory(
            prior_confidence=prior,
            likelihood=likelihood,
            posterior_confidence=posterior,
            evidence_id=evidence_id,
            signal_type=signal_type,
        )
        
        if relationship_id not in self.history:
            self.history[relationship_id] = []
        self.history[relationship_id].append(history_entry)
        
        return posterior, history_entry
    
    def get_confidence_history(self, relationship_id: str) -> list[ConfidenceHistory]:
        """Get confidence history for a relationship."""
        return self.history.get(relationship_id, [])
    
    def compute_signal_weights(self, signals: list[dict[str, Any]]) -> dict[str, float]:
        """Compute normalized weights for signals based on reliability and strength."""
        if not signals:
            return {}
        
        weights = {}
        total_weight = 0.0
        
        for signal in signals:
            signal_type = signal.get("signal_type", "generic")
            strength = signal.get("weight", 0.5)
            reliability = signal.get("reliability", 0.8)
            
            # Combined weight = strength * reliability
            combined_weight = strength * reliability
            weights[signal_type] = combined_weight
            total_weight += combined_weight
        
        # Normalize weights
        if total_weight > 0:
            for signal_type in weights:
                weights[signal_type] /= total_weight
        
        return weights
    
    def aggregate_confidence(
        self,
        base_confidence: float,
        signals: list[dict[str, Any]],
        independent_source_count: int = 1,
    ) -> float:
        """Aggregate confidence from multiple signals with source independence."""
        if not signals:
            return base_confidence
        
        signal_weights = self.compute_signal_weights(signals)
        
        # Weighted average of signal strengths
        weighted_confidence = 0.0
        for signal in signals:
            signal_type = signal.get("signal_type", "generic")
            strength = signal.get("weight", 0.5)
            weight = signal_weights.get(signal_type, 0.0)
            weighted_confidence += strength * weight
        
        # Boost confidence based on independent sources
        source_boost = math.log(1 + independent_source_count) / 10.0
        
        # Combine base confidence with weighted signal confidence
        combined = (base_confidence * 0.4) + (weighted_confidence * 0.6) + source_boost
        return max(0.0, min(1.0, combined))


# Global belief engine instance
belief_engine = BeliefEngine()


class ResolveRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class BeliefUpdateRequest(BaseModel):
    relationship_id: str = Field(min_length=1)
    current_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    new_signal_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    signal_reliability: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence_id: str = ""
    signal_type: str = "generic"


@dataclass(frozen=True)
class CandidateRelationship:
    id: str
    investigation_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    confidence_value: float
    supporting_signals: list[str]
    supporting_evidence_ids: list[str]
    signals: list[dict[str, Any]]


class ResolutionAdapter(Protocol):
    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]: ...


class DevelopmentResolver:
    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]:
        del entity_ids
        candidates: list[CandidateRelationship] = []
        for i, source in enumerate(entities):
            for target in entities[i + 1:]:
                score, signals, evidence_ids = _attribute_similarity(source, target)
                if score < threshold:
                    continue
                candidates.append(CandidateRelationship(
                    id=str(uuid4()),
                    investigation_id=investigation_id,
                    source_entity_id=source.get("id", ""),
                    target_entity_id=target.get("id", ""),
                    relationship_type="POSSIBLY_SAME_AS",
                    confidence_value=score,
                    supporting_signals=[s["signal_type"] for s in signals],
                    supporting_evidence_ids=evidence_ids,
                    signals=signals,
                ))
        return candidates


class SplinkResolver:
    """Probabilistic entity resolution via Splink (DuckDB backend)."""

    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]:
        del entity_ids
        if len(entities) < 2:
            return []
        try:
            import pandas as pd
            from splink import Linker, SettingsCreator, block_on, comparisons
            from splink.backends.duckdb import DuckDBAPI
        except ImportError as exc:
            raise RuntimeError(
                "splink/pandas/duckdb required for MODEL_MODE=real resolution"
            ) from exc

        rows = []
        for entity in entities:
            attrs = entity.get("attributes", {}) or {}
            rows.append({
                "unique_id": str(entity.get("id", "")),
                "label": str(attrs.get("label") or attrs.get("username") or attrs.get("name") or "").lower(),
                "entity_type": str(entity.get("type", "")).lower(),
                "username": str(attrs.get("username") or attrs.get("handle") or "").lower(),
                "evidence": ",".join(entity.get("evidence_ids", []) or []),
            })
        frame = pd.DataFrame(rows)
        if frame["label"].eq("").all() and frame["username"].eq("").all():
            # Splink needs comparable fields; fall back only when attributes are empty.
            return await DevelopmentResolver().resolve(
                investigation_id, entities, [], threshold,
            )

        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=[
                comparisons.ExactMatch("label").configure(term_frequency_adjustments=True),
                comparisons.ExactMatch("entity_type"),
                comparisons.JaroWinklerAtThresholds("username", [0.9, 0.7]),
            ],
            blocking_rules_to_generate_predictions=[
                block_on("entity_type"),
                block_on("label"),
            ],
        )
        linker = Linker(frame, settings, db_api=DuckDBAPI())
        linker.training.estimate_u_using_random_sampling(max_pairs=1_000_000)
        try:
            linker.training.estimate_probability_two_random_records_match(
                [block_on("label")],
                recall=0.7,
            )
            linker.training.estimate_parameters_using_expectation_maximisation(
                block_on("entity_type"),
            )
        except Exception as exc:  # noqa: BLE001 — tiny corpora may not train cleanly
            log.warning("splink EM training incomplete (%s); using u-estimates only", exc)

        predictions = linker.inference.predict(threshold_match_probability=threshold)
        pred_df = predictions.as_pandas_dataframe()
        by_id = {str(e.get("id", "")): e for e in entities}
        candidates: list[CandidateRelationship] = []
        for _, row in pred_df.iterrows():
            left = str(row.get("unique_id_l") or row.get("unique_id_l_1") or "")
            right = str(row.get("unique_id_r") or row.get("unique_id_r_1") or "")
            if not left or not right or left == right:
                continue
            score = float(row.get("match_probability") or 0.0)
            if score < threshold:
                continue
            source = by_id.get(left, {})
            target = by_id.get(right, {})
            evidence_ids = list(dict.fromkeys(
                (source.get("evidence_ids", []) or []) + (target.get("evidence_ids", []) or [])
            ))
            signals = [{
                "id": str(uuid4()),
                "direction": "DIRECTION_SUPPORTING",
                "signal_type": "splink_match_probability",
                "weight": score,
                "raw_score": score,
                "source_service": "ddu-resolution",
                "source_evidence_id": "",
                "details": {"splink": True},
            }]
            candidates.append(CandidateRelationship(
                id=str(uuid4()),
                investigation_id=investigation_id,
                source_entity_id=left,
                target_entity_id=right,
                relationship_type="POSSIBLY_SAME_AS",
                confidence_value=score,
                supporting_signals=["splink_match_probability"],
                supporting_evidence_ids=evidence_ids,
                signals=signals,
            ))
        return candidates


def _attribute_similarity(
    source: dict[str, Any], target: dict[str, Any],
) -> tuple[float, list[dict[str, Any]], list[str]]:
    source_attrs = source.get("attributes", {}) or {}
    target_attrs = target.get("attributes", {}) or {}
    shared_keys = set(source_attrs.keys()) & set(target_attrs.keys())
    matches = 0
    signals: list[dict[str, Any]] = []
    for key in shared_keys:
        if str(source_attrs.get(key, "")).lower() == str(target_attrs.get(key, "")).lower():
            matches += 1
            signals.append({
                "id": str(uuid4()),
                "direction": "DIRECTION_SUPPORTING",
                "signal_type": f"attribute_match:{key}",
                "weight": 1.0 / max(len(shared_keys), 1),
                "raw_score": 1.0,
                "source_service": "ddu-resolution",
                "source_evidence_id": "",
                "details": {"attribute": key},
            })
    total = max(len(shared_keys), 1)
    score = matches / total
    evidence_ids = list(dict.fromkeys(
        (source.get("evidence_ids", []) or []) + (target.get("evidence_ids", []) or [])
    ))
    return score, signals, evidence_ids


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
resolver: ResolutionAdapter = (
    DevelopmentResolver() if model_mode_is_stub() else SplinkResolver()
)


async def _list_entities(investigation_id: str) -> list[dict[str, Any]]:
    response = await graph_client.get(
        "/v1/entities",
        params={"investigation_id": investigation_id},
    )
    response.raise_for_status()
    body = response.json()
    return list(body.get("entities", []))


@app.post("/v1/resolve")
async def resolve(request: ResolveRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:resolve",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    try:
        entities = await _list_entities(request.investigation_id)
        if request.entity_ids:
            wanted = set(request.entity_ids)
            entities = [e for e in entities if e.get("id") in wanted]
        candidates = await resolver.resolve(
            request.investigation_id,
            entities,
            request.entity_ids,
            request.threshold,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:resolve",
            facets=facets,
        ))
        log.exception("entity resolution failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(resolver, DevelopmentResolver) else "splink"
    parameters = {
        "threshold": str(request.threshold),
        "entity_ids": ",".join(request.entity_ids) if request.entity_ids else "all",
    }
    
    # Apply belief engine confidence aggregation
    relationships = []
    for item in candidates:
        # Aggregate confidence using belief engine
        independent_sources = len(set(item.supporting_evidence_ids))
        aggregated_confidence = belief_engine.aggregate_confidence(
            base_confidence=item.confidence_value,
            signals=item.signals,
            independent_source_count=max(1, independent_sources),
        )
        
        relationships.append({
            "id": item.id,
            "investigation_id": item.investigation_id,
            "source_entity_id": item.source_entity_id,
            "target_entity_id": item.target_entity_id,
            "relationship_type": item.relationship_type,
            "confidence": {
                "value": aggregated_confidence,
                "supporting_signals": item.supporting_signals,
                "independent_source_count": independent_sources,
                "computed_by": VERSION.service,
                "computed_at": observed_at,
            },
            "verification_state": "VERIFICATION_STATE_PENDING",
            "supporting_evidence_ids": item.supporting_evidence_ids,
            "evidence_ids": item.supporting_evidence_ids,
            "signals": item.signals,
            "provenance": {
                "investigation_id": item.investigation_id,
                "produced_by_service": VERSION.service,
                "producer_version": VERSION.as_dict(),
                "tool": VERSION.tool,
                "tool_version": VERSION.tool_version,
                "model": VERSION.model,
                "model_version": VERSION.model_version,
                "produced_at": observed_at,
                "run_id": run_id,
                "job_name": "ddu-resolution:resolve",
                "input_evidence_ids": item.supporting_evidence_ids,
                "extraction_method": method,
                "parameters": parameters,
            },
            "created_at": observed_at,
            "updated_at": observed_at,
        })
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:resolve",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.CANDIDATE_RELATIONSHIP",
            )
            for item in relationships
        ],
        facets=facets,
    ))
    return relationships


class ContradictRequest(BaseModel):
    investigation_id: str = Field(min_length=1)


class TemporalSpatialCheck(BaseModel):
    """Request for temporal-spatial consistency check."""
    investigation_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    max_travel_speed_kmh: float = Field(default=1000.0)  # Default to aircraft speed
    time_window_hours: float = Field(default=24.0)


class SourceIndependenceCheck(BaseModel):
    """Request for source independence analysis."""
    investigation_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    similarity_threshold: float = Field(default=0.8)


@app.post("/v1/contradict")
async def contradict(request: ContradictRequest) -> list[dict]:
    """Detect attribute-level contradictions across observation entities."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:contradict",
        facets=facets,
    ))
    try:
        entities = await _list_entities(request.investigation_id)
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:contradict",
            facets=facets,
        ))
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    by_label: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        attrs = entity.get("attributes", {}) or {}
        label = str(attrs.get("label", "")).strip().lower()
        if not label:
            continue
        by_label.setdefault(label, []).append(entity)

    contradictions: list[dict[str, Any]] = []
    for label, group in by_label.items():
        geo_values = {
            str((e.get("attributes") or {}).get("geo", ""))
            for e in group
            if (e.get("attributes") or {}).get("geo")
        }
        type_values = {
            str((e.get("attributes") or {}).get("observation_type", ""))
            for e in group
        }
        if len(geo_values) > 1 or len(type_values) > 1:
            contradictions.append({
                "id": str(uuid4()),
                "investigation_id": request.investigation_id,
                "label": label,
                "entity_ids": [e.get("id") for e in group],
                "reason": "conflicting attributes for shared label",
                "geo_values": sorted(geo_values),
                "observation_types": sorted(type_values),
                "epistemic_class": "EPISTEMIC_CLASS_HYPOTHESIS",
            })

    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:contradict",
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.CONTRADICTION",
            )
            for item in contradictions
        ],
        facets=facets,
    ))
    return contradictions


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers using Haversine formula."""
    from math import asin, atan2, cos, radians, sin, sqrt
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371.0  # Earth radius in kilometers
    return c * r


def _parse_timestamp(ts: str) -> float:
    """Parse timestamp string to Unix timestamp."""
    try:
        from datetime import datetime
        # Try ISO format
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        # Try Unix timestamp
        try:
            return float(ts)
        except Exception:
            return 0.0


def _check_temporal_spatial_consistency(
    entities: list[dict],
    max_speed_kmh: float = 1000.0,
    time_window_hours: float = 24.0,
) -> list[dict]:
    """Check for temporal-spatial inconsistencies across entities."""
    inconsistencies = []
    
    # Extract temporal and spatial data from entities
    entity_events = []
    for entity in entities:
        attrs = entity.get("attributes", {}) or {}
        evidence_ids = entity.get("evidence_ids", []) or []
        
        # Try to extract location and time data
        lat = float(attrs.get("latitude", 0.0))
        lon = float(attrs.get("longitude", 0.0))
        timestamp = _parse_timestamp(attrs.get("timestamp", attrs.get("observed_at", "")))
        
        if lat != 0.0 and lon != 0.0 and timestamp > 0:
            entity_events.append({
                "entity_id": entity.get("id", ""),
                "entity_type": entity.get("type", ""),
                "lat": lat,
                "lon": lon,
                "timestamp": timestamp,
                "evidence_ids": evidence_ids,
            })
    
    # Check pairwise for impossible movement
    for i, event1 in enumerate(entity_events):
        for event2 in entity_events[i + 1:]:
            time_diff = abs(event2["timestamp"] - event1["timestamp"])
            
            # Skip if time difference is too large or too small
            if time_diff > time_window_hours * 3600 or time_diff < 60:  # Skip if >24h or <1min
                continue
            
            distance = _haversine_distance(
                event1["lat"], event1["lon"],
                event2["lat"], event2["lon"],
            )
            
            # Calculate required speed
            time_hours = time_diff / 3600.0
            required_speed = distance / time_hours if time_hours > 0 else 0.0
            
            if required_speed > max_speed_kmh:
                inconsistencies.append({
                    "id": str(uuid4()),
                    "type": "TEMPORAL_SPATIAL_IMPOSSIBLE_MOVEMENT",
                    "entity1_id": event1["entity_id"],
                    "entity2_id": event2["entity_id"],
                    "distance_km": round(distance, 2),
                    "time_diff_hours": round(time_hours, 2),
                    "required_speed_kmh": round(required_speed, 2),
                    "max_allowed_speed_kmh": max_speed_kmh,
                    "evidence_ids": list(set(event1["evidence_ids"] + event2["evidence_ids"])),
                    "reason": f"Required speed {required_speed:.1f} km/h exceeds maximum {max_speed_kmh} km/h",
                    "epistemic_class": "EPISTEMIC_CLASS_CONTRADICTION",
                })
    
    return inconsistencies


def _analyze_source_independence(
    evidence_ids: list[str],
    entities: list[dict],
    threshold: float = 0.8,
) -> dict:
    """Analyze source independence across evidence items."""
    if not evidence_ids:
        return {
            "independent_source_count": 0,
            "total_evidence": 0,
            "independence_score": 0.0,
            "clusters": [],
            "reason": "No evidence provided",
        }
    
    # Extract source information from evidence metadata
    evidence_sources = {}
    for entity in entities:
        attrs = entity.get("attributes", {}) or {}
        entity_evidence_ids = entity.get("evidence_ids", []) or []
        
        source = attrs.get("source", attrs.get("acquired_by", "unknown"))
        for evidence_id in entity_evidence_ids:
            if evidence_id in evidence_ids:
                if evidence_id not in evidence_sources:
                    evidence_sources[evidence_id] = []
                evidence_sources[evidence_id].append(source)
    
    # Cluster evidence by source similarity
    clusters = []
    used_evidence = set()
    
    for evidence_id in evidence_ids:
        if evidence_id in used_evidence:
            continue
        
        sources = evidence_sources.get(evidence_id, ["unknown"])
        cluster = [evidence_id]
        used_evidence.add(evidence_id)
        
        # Find evidence with similar sources
        for other_id in evidence_ids:
            if other_id in used_evidence:
                continue
            
            other_sources = evidence_sources.get(other_id, ["unknown"])
            
            # Calculate Jaccard similarity
            set1 = set(sources)
            set2 = set(other_sources)
            intersection = set1 & set2
            union = set1 | set2
            similarity = len(intersection) / len(union) if union else 0.0
            
            if similarity >= threshold:
                cluster.append(other_id)
                used_evidence.add(other_id)
        
        if cluster:
            clusters.append({
                "evidence_ids": cluster,
                "sources": list(set(s for ev in cluster for s in evidence_sources.get(ev, ["unknown"]))),
                "size": len(cluster),
            })
    
    independent_source_count = len(clusters)
    independence_score = independent_source_count / len(evidence_ids) if evidence_ids else 0.0
    
    return {
        "independent_source_count": independent_source_count,
        "total_evidence": len(evidence_ids),
        "independence_score": independence_score,
        "clusters": clusters,
        "evidence_source_mapping": evidence_sources,
    }


@app.post("/v1/contradict/temporal-spatial")
async def contradict_temporal_spatial(request: TemporalSpatialCheck) -> dict:
    """Detect temporal-spatial contradictions across entity movements."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:temporal-spatial-contradict",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    
    try:
        entities = await _list_entities(request.investigation_id)
        if request.entity_id:
            entities = [e for e in entities if e.get("id") == request.entity_id]
        
        inconsistencies = _check_temporal_spatial_consistency(
            entities,
            max_speed_kmh=request.max_travel_speed_kmh,
            time_window_hours=request.time_window_hours,
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:temporal-spatial-contradict",
            facets=facets,
        ))
        log.exception("temporal-spatial contradiction check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:temporal-spatial-contradict",
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.CONTRADICTION",
            )
            for item in inconsistencies
        ],
        facets=facets,
    ))
    
    return {
        "investigation_id": request.investigation_id,
        "entity_id": request.entity_id,
        "inconsistencies": inconsistencies,
        "total_inconsistencies": len(inconsistencies),
        "parameters": {
            "max_travel_speed_kmh": request.max_travel_speed_kmh,
            "time_window_hours": request.time_window_hours,
        },
    }


@app.post("/v1/resolution/source-independence")
async def check_source_independence(request: SourceIndependenceCheck) -> dict:
    """Analyze source independence across evidence items."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:source-independence",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    
    try:
        entities = await _list_entities(request.investigation_id)
        analysis = _analyze_source_independence(
            evidence_ids=request.evidence_ids,
            entities=entities,
            threshold=request.similarity_threshold,
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:source-independence",
            facets=facets,
        ))
        log.exception("source independence check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:source-independence",
        outputs=[Output(
            namespace=request.investigation_id,
            name=f"source_independence_{request.investigation_id}",
            type="DDU.SOURCE_INDEPENDENCE",
        )],
        facets=facets,
    ))
    
    return {
        "investigation_id": request.investigation_id,
        "evidence_ids": request.evidence_ids,
        "analysis": analysis,
        "parameters": {
            "similarity_threshold": request.similarity_threshold,
        },
    }


@app.post("/v1/belief/update")
async def update_belief(request: BeliefUpdateRequest) -> dict:
    """Update confidence using Bayesian inference."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.relationship_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:belief-update",
        inputs=[Input(
            namespace=request.relationship_id,
            name=request.relationship_id,
            type="DDU.RELATIONSHIP",
        )],
        facets=facets,
    ))
    
    new_confidence, history_entry = belief_engine.update_belief(
        relationship_id=request.relationship_id,
        current_confidence=request.current_confidence,
        new_signal_strength=request.new_signal_strength,
        signal_reliability=request.signal_reliability,
        evidence_id=request.evidence_id,
        signal_type=request.signal_type,
    )
    
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:belief-update",
        outputs=[Output(
            namespace=request.relationship_id,
            name=request.relationship_id,
            type="DDU.BELIEF_UPDATE",
        )],
        facets=facets,
    ))
    
    return {
        "relationship_id": request.relationship_id,
        "prior_confidence": request.current_confidence,
        "posterior_confidence": new_confidence,
        "belief_change": new_confidence - request.current_confidence,
        "history_entry": {
            "prior_confidence": history_entry.prior_confidence,
            "likelihood": history_entry.likelihood,
            "posterior_confidence": history_entry.posterior_confidence,
            "evidence_id": history_entry.evidence_id,
            "signal_type": history_entry.signal_type,
            "timestamp": history_entry.timestamp,
        },
    }


@app.get("/v1/belief/history/{relationship_id}")
async def get_belief_history(relationship_id: str) -> dict:
    """Get confidence history for a relationship."""
    history = belief_engine.get_confidence_history(relationship_id)
    
    return {
        "relationship_id": relationship_id,
        "history": [
            {
                "prior_confidence": h.prior_confidence,
                "likelihood": h.likelihood,
                "posterior_confidence": h.posterior_confidence,
                "evidence_id": h.evidence_id,
                "signal_type": h.signal_type,
                "timestamp": h.timestamp,
            }
            for h in history
        ],
        "total_updates": len(history),
    }


@app.post("/v1/belief/aggregate")
async def aggregate_confidence(
    base_confidence: float = 0.5,
    signals: list[dict] = [],
    independent_source_count: int = 1,
) -> dict:
    """Aggregate confidence from multiple signals."""
    aggregated = belief_engine.aggregate_confidence(
        base_confidence=base_confidence,
        signals=signals,
        independent_source_count=independent_source_count,
    )
    
    signal_weights = belief_engine.compute_signal_weights(signals)
    
    return {
        "base_confidence": base_confidence,
        "aggregated_confidence": aggregated,
        "confidence_change": aggregated - base_confidence,
        "signal_weights": signal_weights,
        "independent_source_count": independent_source_count,
    }


def main() -> None:
    port = int(os.environ.get("PORT", 8111))
    log.info("ddu-resolution listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
