# DDU — Digital Detective Unit

> **Start with one clue. Build the intelligence picture.**

DDU is an open-source-first, multimodal investigation and intelligence platform. It turns fragmented data — an image, a username, a URL, a document, a video, an audio clip — into a structured, explorable, evidence-backed intelligence graph.

## Vision

Modern investigation work is fractured across dozens of single-purpose tools: an object detector here, a username search there, a geolocation model somewhere else, an OSINT scanner, a graph database, a web scraper. Each produces disconnected results. The investigator is left to manually stitch clues together, with no consistent provenance, no confidence model, and no record of how a conclusion was reached.

DDU closes that gap.

DDU is not another object detector, username search tool, geolocation model, OSINT scanner, graph database, or web scraper. It is the **intelligence lifecycle that connects them**:

> **Ingest → Observe → Extract → Discover → Resolve → Correlate → Enrich → Verify → Connect → Investigate**

One clue enters DDU. An evidence-backed intelligence graph emerges.

## What DDU Builds

A continuously evolving knowledge graph where every relationship carries:

- **Source** — where it came from
- **Provenance** — which tool and model produced it
- **Timestamp** — when it was observed or inferred
- **Extraction method** — how it was derived
- **Confidence** — how strongly supported
- **Verification state** — observed, inferred, confirmed, contradicted

DDU never collapses machine-generated conclusions into "truth." The platform explicitly distinguishes:

- **Observation** — directly detected
- **Claim** — asserted by an external source
- **Inference** — machine-generated
- **Hypothesis** — possible explanation requiring more evidence
- **Fact** — met a defined verification threshold
- **Contradiction** — evidence incompatible with another claim

These distinctions are exposed visually and programmatically throughout the system.

## Core Capabilities

- **Multimodal perception** — object detection, segmentation, video tracking, OCR, speech transcription, face/person similarity
- **OSINT discovery** — username-to-account discovery, OSINT enrichment, public media acquisition, controlled web capture
- **Image geolocation** — visual geolocation producing ranked location hypotheses, never confirmed locations
- **Multimodal entity resolution** — probabilistic record linkage combined with visual, semantic, geographic, temporal, and graph-context signals
- **Vector intelligence** — similarity search across images, objects, text, documents, and entities
- **Ontology-native knowledge model** — canonical ontology plus a temporal knowledge graph for evolving intelligence
- **Evidence provenance** — processing lineage plus evidence-level provenance for every relationship
- **Confidence-aware reasoning** — confidence that accounts for supporting signals, independent sources, contradictions, and temporal/geographic consistency
- **Agentic investigation** — LangGraph-powered workflows with explicit stop conditions, never indefinite recursion
- **Human investigation workspace** — graph, map, timeline, evidence viewer, and command dashboard, with bidirectional highlighting and human control over uncertain conclusions

## Proprietary Moat

The strongest proprietary component is the **DDU Intelligence Correlation Engine**. It answers the question that no single OSS tool can answer:

> **Are these clues actually connected?**

Inputs: visual similarity, semantic similarity, structured record similarity, username similarity, geographic compatibility, temporal compatibility, graph relationships, source reliability, independent corroboration, contradicting evidence.

Output: candidate relationships with confidence and fully inspectable supporting and contradicting evidence paths.

This is the difference between DDU and a collection of disconnected OSINT tools.

## Open-Source Foundation

DDU is built on established open-source projects, integrated behind stable DDU-defined service contracts:

- **Perception:** Grounded SAM 2, MMDetection, PaddleOCR, Whisper, CompreFace
- **Geolocation:** GeoCLIP
- **Discovery:** Sherlock, SpiderFoot, gallery-dl, Browsertrix Crawler
- **Vector:** Qdrant
- **Entity resolution:** Splink
- **Knowledge:** OpenSPG, Graphiti, Neo4j
- **Provenance:** OpenLineage
- **Orchestration:** LangGraph
- **Visualization:** Cytoscape.js, MapLibre GL JS
- **Storage:** MinIO

DDU owns the intelligence lifecycle. The open-source projects own their capabilities. Each project is an replaceable implementation of a DDU service contract.

## Status

**Pre-Alpha / runnable local stack.** Product Development Document and engineering roadmap are in this repository. Use `make tier1` then `./infra/scripts/dev-services.sh` (or `make up` for containerized DDU services).

The `3D-scene` branch also contains the DDU Mirror Engineer D experience:
a react-three-fiber exposure graph, human approval controls, evidence drawer,
MapLibre view, remediation simulation, session wipe, and PII-disciplined
ElevenLabs voice adapter. See [`ui/ddu-ui/README.md`](./ui/ddu-ui/README.md),
the [`demo script`](./docs/engineer-d-demo-script.md), and the
[`system card`](./docs/system-card-mirror-experience.md).

## Documents

- [`main-pdd.md`](./main-pdd.md) — Product Development Document (full product spec)
- [`engineering-roadmap.md`](./engineering-roadmap.md) — Engineering roadmap, integration tiers, phases, service contracts
- [`open-source/`](./open-source/) — Reference clones of foundational open-source projects

## Primary Users

Investigators, security teams, researchers, intelligence analysts, fraud teams, journalists, enterprise risk teams.

## Product Identity

DDU is an operational system, not a consumer AI assistant. The interface communicates precision, evidence, control, correlation, and investigation. The visual language emphasizes the distinction between observed, inferred, confirmed, and contradicted.

---

> **One clue enters DDU. An evidence-backed intelligence graph emerges.**
