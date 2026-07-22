# DDU

## Digital Detective Unit

### Product Development Document

**Product Name:** DDU
**Full Name:** Digital Detective Unit
**Category:** Multimodal Investigation, OSINT, Knowledge Graph, and Intelligence Platform
**Stage:** Concept / Pre-Alpha
**Architecture:** Open-source-first, ontology-native, evidence-backed
**Primary Users:** Investigators, security teams, researchers, intelligence analysts, fraud teams, journalists, enterprise risk teams

---

# 1. Executive Summary

DDU is a multimodal investigation and intelligence platform designed to turn fragmented data into a structured, explorable, evidence-backed intelligence graph.

A user begins an investigation with one or more clues:

* Image
* Video
* Audio
* Username
* Social profile
* URL
* Document
* Location
* Public web entity

DDU then coordinates specialized open-source systems to extract information, discover related public data, identify candidate entities, connect relationships, analyze geographic and temporal patterns, and construct an evolving ontology around the investigation.

Instead of returning disconnected search results, DDU creates an intelligence model connecting:

* People
* Usernames
* Accounts
* Organizations
* Images
* Videos
* Audio
* Documents
* Posts
* Objects
* Vehicles
* Locations
* Events
* Observations
* Sources
* Evidence
* Claims
* Hypotheses

Every significant relationship should retain:

* Source
* Provenance
* Timestamp
* Extraction method
* Confidence
* Verification status

The central product philosophy is:

> **Start with one clue. Build the intelligence picture.**

DDU is not intended to treat every machine-generated conclusion as fact. The system explicitly distinguishes observations, claims, inferred relationships, hypotheses, and verified facts.

---

# 2. Product Vision

Build an open-source-first investigation operating system capable of transforming multimodal data and public information into a continuously evolving knowledge graph.

The core lifecycle is:

**Ingest → Observe → Extract → Discover → Resolve → Correlate → Enrich → Verify → Connect → Investigate**

DDU should help answer:

* What entities are present?
* What objects appear across the evidence?
* What text can be extracted from images and documents?
* What locations are plausible?
* Where else does this username appear?
* What publicly available data is associated with these entities?
* Are two discovered accounts likely connected?
* Which objects appear in multiple images or videos?
* Which entities share geographic or temporal overlap?
* What evidence supports each relationship?
* Which evidence contradicts an existing conclusion?
* How has the investigation evolved?
* What clue should be investigated next?

---

# 3. Core Product Principle

DDU must never collapse all intelligence into a single concept of "truth."

The platform should represent:

## Observation

Something directly detected or extracted.

Example:

> OCR detected the text "Austin" in Image_14.

---

## Claim

Something asserted by an external source.

Example:

> Profile_22 states that the account owner is located in Austin.

---

## Inference

A machine-generated conclusion.

Example:

> GeoCLIP predicts Central Texas as a likely location.

---

## Hypothesis

A possible explanation requiring additional evidence.

Example:

> Account_22 may belong to Person_7.

---

## Fact

Information that has met a defined verification threshold.

Example:

> Image metadata contains GPS coordinates corresponding to Austin, Texas.

---

## Contradiction

Evidence incompatible with another claim or hypothesis.

Example:

> A timestamped observation places the entity in Dallas during the same period.

DDU should expose these distinctions visually and programmatically.

---

# 4. Open-Source Technology Foundation

DDU will use the following projects as foundational components.

## GeoCLIP

Repository:

VicenteVivan/geo-clip

Role:

Visual geolocation.

DDU uses GeoCLIP to generate candidate geographic locations from images.

Output should be treated as:

**Location Hypothesis**

rather than confirmed location.

---

## SpiderFoot

Repository:

smicallef/spiderfoot

Role:

Automated OSINT enrichment.

SpiderFoot acts as a broad enrichment engine for supported public intelligence sources.

DDU should integrate SpiderFoot as an investigation tool rather than embedding its entire application directly into the frontend.

---

## Sherlock

Repository:

sherlock-project/sherlock

Role:

Username-based account discovery.

Input:

Username

Output:

Candidate public accounts across supported services.

Discovered accounts should initially become:

**CandidateAccount**

entities.

They must not automatically be linked to a confirmed Person.

---

## gallery-dl

Repository:

mikf/gallery-dl

Role:

Public media acquisition from supported websites.

Given supported profile, gallery, or media URLs, gallery-dl can feed discovered media into DDU's processing pipeline.

Collected media is sent to:

* Grounded SAM 2
* MMDetection
* PaddleOCR
* GeoCLIP
* Qdrant

where appropriate.

---

## Grounded SAM 2

Repository:

IDEA-Research/Grounded-SAM-2

Role:

Open-vocabulary visual detection, segmentation, and video object tracking.

DDU uses Grounded SAM 2 for:

* Object discovery
* Object segmentation
* Open-vocabulary detection
* Video tracking
* Frame-level observations

This is the primary visual intelligence engine.

---

## MMDetection

Repository:

open-mmlab/mmdetection

Role:

Advanced and specialized computer vision model framework.

MMDetection supports cases where DDU requires:

* Specialized object detectors
* Custom trained models
* Domain-specific detection
* Instance segmentation
* Detection pipelines not covered by the default Grounded SAM workflow

Grounded SAM 2 and MMDetection should be complementary.

Grounded SAM 2:

General/open-vocabulary discovery.

MMDetection:

Specialized and trained detection.

---

## PaddleOCR

Repository:

PaddlePaddle/PaddleOCR

Role:

OCR and document intelligence.

DDU uses PaddleOCR for:

* Text in photographs
* Street signs
* Storefronts
* Screenshots
* Documents
* Scanned evidence
* Layout-aware extraction

Detected text becomes an evidence-linked observation.

---

## Whisper

Repository:

openai/whisper

Role:

Speech transcription.

DDU uses Whisper for:

* Audio transcription
* Video speech extraction
* Timestamped transcripts
* Language detection

Transcripts are indexed and converted into searchable evidence.

---

## Splink

Repository:

moj-analytical-services/splink

Role:

Probabilistic entity resolution and record linkage.

Splink forms the structured-data foundation of DDU's Entity Resolution Engine.

It helps determine whether records may represent the same underlying entity.

DDU should extend this with multimodal evidence.

---

## Qdrant

Repository:

qdrant/qdrant

Role:

Vector database and similarity search.

DDU stores embeddings for:

* Images
* Object crops
* Text
* Documents
* Posts
* Entities
* Descriptions

Qdrant supports queries such as:

* Find visually similar objects.
* Find similar images.
* Find semantically related documents.
* Find posts describing similar events.

Similarity results remain candidate relationships until validated.

---

## OpenSPG

Repository:

OpenSPG/openspg

Role:

Ontology and structured knowledge representation.

OpenSPG provides the foundation for DDU's canonical knowledge model.

The ontology describes:

* What entities exist
* What relationships are permitted
* How knowledge is classified
* How domain concepts connect

OpenSPG represents DDU's structured intelligence layer.

---

## Graphiti

Repository:

getzep/graphiti

Role:

Temporal and continuously evolving knowledge graph.

Graphiti manages knowledge that changes over time.

DDU uses Graphiti to model:

* New observations
* Changing relationships
* Temporal facts
* Updated hypotheses
* Historical states

OpenSPG and Graphiti serve different roles:

**OpenSPG**

Defines the canonical ontology.

**Graphiti**

Maintains evolving temporal knowledge.

---

## OpenLineage

Repository:

OpenLineage/OpenLineage

Role:

Data lineage and processing provenance.

DDU uses OpenLineage concepts to record:

* Where data originated
* Which process created a derived object
* Which tool processed it
* Which model version was used
* Which downstream outputs depend on it

This provides process-level provenance.

DDU should additionally implement evidence-level provenance for investigative relationships.

---

## LangGraph

Repository:

langchain-ai/langgraph

Role:

Investigation agent orchestration.

LangGraph coordinates investigation workflows.

Example:

Image received.

Agent workflow:

1. Read metadata.
2. Run OCR.
3. Run object detection.
4. Run geolocation.
5. Search extracted usernames.
6. Trigger OSINT enrichment.
7. Search the existing graph.
8. Resolve candidate entities.
9. Generate hypotheses.
10. Identify missing evidence.

Agents operate under explicit limits.

---

## Cytoscape.js

Repository:

cytoscape/cytoscape.js

Role:

Interactive relationship graph visualization.

Cytoscape.js powers the primary investigation graph.

It displays:

Person ↔ Account ↔ Username ↔ Post ↔ Media ↔ Object ↔ Location ↔ Event

---

## MapLibre GL JS

Repository:

maplibre/maplibre-gl-js

Role:

Geospatial investigation interface.

MapLibre displays:

* Observations
* Candidate locations
* Confirmed locations
* Geographic clusters
* Events
* Movement patterns
* Location confidence

---

# 5. DDU System Architecture

```text
                    INPUT SOURCES

 Images
 Videos
 Audio
 Documents
 Usernames
 URLs
 Public Profiles
 Public Web Data
       │
       ▼
┌────────────────────────────────────────────┐
│             DDU INGESTION LAYER            │
└─────────────────────┬──────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────┐
│          MULTIMODAL PERCEPTION             │
│                                            │
│ Grounded SAM 2  → object discovery         │
│ MMDetection     → specialized detection    │
│ PaddleOCR       → OCR / document text      │
│ Whisper         → speech transcription     │
└─────────────────────┬──────────────────────┘
                      │
                      ▼
                ENTITY EXTRACTION
                      │
                      ▼
┌────────────────────────────────────────────┐
│          ENTITY RESOLUTION ENGINE          │
│                                            │
│ Splink                                     │
│ Vector Similarity                          │
│ Graph Context                              │
│ Geographic Compatibility                   │
│ Temporal Compatibility                     │
└───────────────┬────────────────────────────┘
                │
         ┌──────┴──────┐
         ▼             ▼
      QDRANT       EVIDENCE STORE
   Vector Search      Raw Sources
         │             │
         └──────┬──────┘
                ▼
┌────────────────────────────────────────────┐
│             ENRICHMENT LAYER               │
│                                            │
│ GeoCLIP      → geolocation                 │
│ Sherlock     → username discovery          │
│ SpiderFoot   → OSINT enrichment            │
│ gallery-dl   → media acquisition           │
└─────────────────────┬──────────────────────┘
                      │
                      ▼
             EVIDENCE EVALUATION
                      │
                      ▼
                  OPENSPG
             Canonical Ontology
                      │
                      ▼
                  GRAPHITI
          Temporal Knowledge Graph
                      │
                      ▼
             GRAPH PERSISTENCE
                      │
                      ▼
                  LANGGRAPH
          Investigation Orchestrator
                      │
         ┌────────────┼─────────────┐
         ▼            ▼             ▼
     CYTOSCAPE      MAPLIBRE      TIMELINE
       Graph           Map       Temporal View
         │            │             │
         └────────────┼─────────────┘
                      ▼
               EVIDENCE VIEWER
```

---

# 6. Investigation Model

The top-level organizational object in DDU is an:

**Investigation**

Each investigation contains:

* Seeds
* Entities
* Evidence
* Observations
* Claims
* Hypotheses
* Relationships
* Sources
* Agent actions
* Timeline
* Geographic context

Example:

Investigation:

Case 001

Seed:

Image_001

DDU analyzes the image and begins expanding the investigation.

---

# 7. Investigation Seeds

DDU should initially support:

## Image

Triggers:

* Metadata extraction
* Grounded SAM 2
* MMDetection where required
* PaddleOCR
* GeoCLIP
* Qdrant similarity search

---

## Video

Triggers:

* Frame extraction
* Grounded SAM 2 tracking
* MMDetection
* OCR
* Whisper
* Object persistence analysis
* Location inference

---

## Audio

Triggers:

* Whisper
* Entity extraction
* Language analysis
* Timeline creation

---

## Username

Triggers:

* Sherlock
* SpiderFoot enrichment where supported
* Candidate account creation
* Entity resolution

---

## URL

Triggers:

* Source classification
* Metadata extraction
* gallery-dl where supported
* SpiderFoot modules
* Content ingestion

---

## Document

Triggers:

* PaddleOCR when required
* Text extraction
* Entity extraction
* Qdrant indexing
* Ontology ingestion

---

# 8. Visual Intelligence

DDU's visual pipeline consists of two complementary systems.

## Grounded SAM 2

Used for:

* General object discovery
* Text-prompted detection
* Segmentation
* Video object tracking

Example:

Video_04

contains:

Vehicle_Observation_11

tracked from:

00:04:21

to:

00:04:47

---

## MMDetection

Used for:

* Domain-specific detectors
* Custom object classes
* High-specialization detection
* Models trained for specific operational environments

Example:

A custom MMDetection model could identify specialized object subclasses not reliably captured by open-vocabulary detection.

---

# 9. Image Geolocation

DDU uses GeoCLIP as the visual geolocation engine.

Input:

Image

Output:

Ranked geographic candidates.

Example:

Candidate 1:

Austin, Texas

Candidate 2:

San Antonio, Texas

Candidate 3:

Dallas, Texas

DDU should combine GeoCLIP with:

* EXIF
* OCR
* Detected language
* Visible signs
* Landmark evidence
* Other geographic clues

Final output:

**Location Hypothesis**

Example:

Austin, Texas

Confidence:

0.84

Supporting evidence:

GeoCLIP prediction

OCR: "Austin"

Architecture clue

Independent source count:

2

---

# 10. Username and Account Discovery

Sherlock serves as the primary username discovery engine.

Input:

example_username

Output:

Candidate public profiles.

Each result becomes:

CandidateAccount

Example:

CandidateAccount_17

Platform:

GitHub

Username:

example_username

URL:

...

Discovery Method:

Sherlock

Confidence:

Discovery confirmed

Identity Confidence:

Unknown

This distinction matters.

Sherlock can confirm that an account exists.

It cannot confirm that two accounts belong to the same real person.

---

# 11. Automated OSINT Enrichment

SpiderFoot acts as DDU's general OSINT enrichment engine.

DDU should expose selected SpiderFoot capabilities as modular tools.

Example workflow:

Username discovered

↓

Domain discovered

↓

SpiderFoot enrichment

↓

New entities discovered

↓

Ontology ingestion

Possible outputs:

* Domain
* Email
* Organization
* IP
* Public identifier
* Connected service

Every result receives provenance information.

---

# 12. Social Media and Media Acquisition

gallery-dl acts as a public media acquisition layer for supported sources.

Workflow:

Sherlock finds candidate account.

↓

Platform URL sent to collector router.

↓

gallery-dl retrieves accessible supported media.

↓

Media stored as evidence.

↓

Grounded SAM 2 analyzes objects.

↓

PaddleOCR extracts visible text.

↓

GeoCLIP analyzes location.

↓

Qdrant generates embeddings.

↓

Graph relationships update.

The collector must not bypass authorization controls or private access restrictions.

---

# 13. Entity Resolution Engine

This is a core DDU capability.

The problem:

Sherlock finds:

Account_A

SpiderFoot finds:

Identifier_B

Image analysis finds:

Person_Observation_C

Another source finds:

Username_D

Are these related?

DDU should calculate candidate relationships using:

* Splink record linkage
* Username similarity
* Structured attribute matching
* Qdrant embedding similarity
* Geographic compatibility
* Temporal compatibility
* Graph proximity
* Shared identifiers
* Source reliability

Output:

Account_A

POSSIBLY_BELONGS_TO

Person_7

Confidence:

0.76

Supporting signals:

Username match

Location overlap

Shared URL

Contradicting signals:

Different profile description

DDU should never automatically perform high-impact identity merges based only on weak similarity.

---

# 14. Multimodal Entity Resolution

Splink alone is not enough.

DDU should implement a proprietary layer above Splink.

## DDU Entity Resolution Engine

Inputs:

Structured similarity

*

Visual similarity

*

Semantic similarity

*

Temporal compatibility

*

Geographic compatibility

*

Graph context

*

Source reliability

Output:

Association probability.

This should become one of DDU's primary proprietary advantages.

---

# 15. Vector Intelligence

Qdrant provides similarity search.

Collections may include:

## Image Embeddings

Queries:

Find similar images.

---

## Object Embeddings

Queries:

Find visually similar objects.

---

## Text Embeddings

Queries:

Find related posts.

---

## Document Embeddings

Queries:

Find related reports.

---

## Entity Embeddings

Queries:

Find entities with similar contextual profiles.

Vector similarity never directly creates verified relationships.

It creates:

CandidateRelationship

---

# 16. DDU Ontology

OpenSPG provides the canonical ontology layer.

Core entity types:

Person

Account

Username

Organization

Location

Object

Vehicle

Image

Video

Audio

Document

Post

Event

Observation

Evidence

Source

Claim

Hypothesis

Investigation

---

# 17. Relationship Model

Example relationships:

OWNS

USES

APPEARS_IN

OBSERVED_AT

POSTED

MENTIONED_IN

CONNECTED_TO

ASSOCIATED_WITH

LOCATED_AT

POSSIBLY_SAME_AS

SUPPORTED_BY

CONTRADICTED_BY

DERIVED_FROM

EXTRACTED_FROM

DISCOVERED_BY

Every relationship contains:

* Confidence
* Timestamp
* Source
* Evidence references
* Extraction method
* Tool version
* Verification state

---

# 18. Temporal Intelligence

Graphiti manages evolving knowledge.

Example:

Day 1

Account_A

POSSIBLY_BELONGS_TO

Person_X

Confidence:

0.48

Day 4

New evidence increases confidence:

0.73

Day 9

Contradictory location data appears:

0.55

DDU preserves this evolution.

The historical state should remain queryable.

---

# 19. Provenance

OpenLineage provides a foundation for processing lineage.

Example:

Image_22

processed_by

PaddleOCR vX

↓

TextObservation_91

↓

EntityExtraction

↓

LocationHypothesis_18

Users should be able to answer:

Where did this conclusion come from?

Which model created it?

Which evidence was used?

What downstream objects depend on it?

---

# 20. Evidence System

DDU should maintain an immutable or append-only evidence store wherever practical.

Evidence types:

* Image
* Video
* Audio
* Document
* Web snapshot
* Profile
* Post
* Metadata
* Model output

Each evidence object contains:

Source

Acquisition time

Original timestamp

Hash

MIME type

Processing history

Origin URL where applicable

Investigation ID

---

# 21. Confidence Engine

Confidence should not be calculated by blindly averaging model probabilities.

DDU should consider:

* Number of supporting signals
* Number of independent sources
* Source reliability
* Evidence freshness
* Model confidence
* Contradicting evidence
* Temporal consistency
* Geographic consistency

Example:

Hypothesis:

Entity_A associated with Location_B

Support:

GeoCLIP

OCR

Social metadata

Contradiction:

Recent observation elsewhere

Result:

Confidence 0.71

---

# 22. Investigation Agent

LangGraph powers the agentic investigation workflow.

The DDU agent acts as an:

**Digital Investigator**

The agent does not simply answer questions.

It coordinates investigative tools.

Example:

User uploads an image.

Agent:

1. Extract metadata.
2. Run OCR.
3. Analyze objects.
4. Generate location candidates.
5. Search existing graph.
6. Extract usernames.
7. Run Sherlock.
8. Trigger SpiderFoot where appropriate.
9. Acquire supported public media.
10. Analyze newly discovered media.
11. Resolve candidate entities.
12. Update ontology.
13. Generate unresolved hypotheses.
14. Stop when predefined investigation conditions are met.

---

# 23. Agent Stop Conditions

Agents must have explicit stop conditions.

Stop when:

* Investigation depth limit reached
* Tool budget reached
* No meaningful new entities discovered
* Confidence threshold reached
* Required evidence collected
* Investigation scope boundary reached
* Human confirmation required

The system should never indefinitely recurse through discovered entities.

---

# 24. Graph Interface

Cytoscape.js powers the relationship workspace.

Example graph:

```text
Person
  │
  ├── uses ───────── Account
  │                     │
  │                     └── posted ── Image
  │                                    │
  │                                    ├── contains ── Vehicle
  │                                    │
  │                                    └── observed_at ── Location
  │
  └── associated_with ── Organization
```

Users can:

* Expand nodes
* Collapse branches
* Filter entity types
* Filter confidence
* Search relationships
* Find shortest paths
* Compare entities
* Inspect evidence
* Accept/reject candidate relationships

---

# 25. Map Interface

MapLibre GL JS powers geographic intelligence.

Layers:

Confirmed Locations

Candidate Locations

Observations

Events

Media

Clusters

Routes

Confidence Areas

Selecting an entity in Cytoscape should highlight corresponding map observations.

Selecting a map observation should highlight the corresponding graph nodes.

---

# 26. Timeline

DDU should build a custom temporal interface synchronized with:

* Graph
* Map
* Evidence

Users can scrub through time.

Example:

January

Account discovered.

February

Image observed.

March

Vehicle associated.

April

Location hypothesis contradicted.

Graph and map update according to the selected date.

---

# 27. Unified Investigation Workspace

Primary navigation:

## COMMAND

Investigation overview.

## GRAPH

Relationship analysis.

## MAP

Geospatial analysis.

## TIMELINE

Temporal analysis.

## EVIDENCE

Source inspection.

## ENTITIES

Entity database.

## SOURCES

Source management.

## HYPOTHESES

Unresolved conclusions.

## AGENT

Investigation automation.

---

# 28. DDU Command View

The default investigation dashboard should summarize:

Investigation Status

Entities Discovered

Evidence Items

Candidate Relationships

Confirmed Relationships

Open Hypotheses

Contradictions

Geographic Candidates

Agent Activity

The objective is to give the investigator a concise intelligence picture before entering individual analytical views.

---

# 29. MVP

The MVP should avoid integrating every feature simultaneously.

## MVP Inputs

Image

Username

URL

---

## MVP Processing

Grounded SAM 2

PaddleOCR

GeoCLIP

Sherlock

SpiderFoot

gallery-dl

---

## MVP Intelligence

Basic entity extraction

Basic entity resolution

Qdrant similarity

OpenSPG ontology

Graph relationships

Evidence provenance

---

## MVP Interface

Cytoscape.js graph

MapLibre map

Evidence viewer

Investigation dashboard

---

# 30. MVP Workflow A

## Image Investigation

User uploads image.

DDU:

1. Stores original evidence.
2. Extracts metadata.
3. Runs Grounded SAM 2.
4. Extracts text using PaddleOCR.
5. Runs GeoCLIP.
6. Embeds image and objects into Qdrant.
7. Creates ontology entities.
8. Generates candidate relationships.
9. Displays entities in Cytoscape.
10. Displays location candidates in MapLibre.

---

# 31. MVP Workflow B

## Username Investigation

User enters username.

DDU:

1. Runs Sherlock.
2. Creates CandidateAccount entities.
3. Runs supported SpiderFoot enrichment.
4. Routes supported public media sources to gallery-dl.
5. Processes acquired media.
6. Generates candidate identity relationships.
7. Stores evidence.
8. Displays account network.

---

# 32. Phase 2

Add:

* Video ingestion
* Grounded SAM video tracking
* MMDetection custom models
* Whisper audio processing
* Advanced multimodal entity resolution
* Graphiti temporal intelligence
* Timeline interface
* Contradiction engine
* Advanced social connectors

---

# 33. Phase 3

Add:

* LangGraph autonomous investigation workflows
* Investigation templates
* Natural-language investigation queries
* Collaborative investigations
* Human verification workflows
* Report generation
* Graph snapshots
* Investigation replay
* Plugin SDK
* Custom ontology builder
* Air-gapped deployment

---

# 34. Natural-Language Investigation

Future DDU versions should support queries such as:

"Show every account potentially connected to this username."

"Find images containing vehicles visually similar to this one."

"Which evidence connects these entities?"

"Show all observations associated with Austin."

"Show relationships with confidence below 70%."

"What changed in this investigation during the last week?"

"Which hypotheses currently have contradictory evidence?"

The DDU query engine determines whether the question requires:

Graph search

Vector search

Temporal search

Geospatial search

or

Evidence retrieval.

---

# 35. Security Architecture

Required:

RBAC

Investigation-level access

Source-level permissions

Encryption at rest

Encryption in transit

Audit logs

Secrets management

Data retention policies

Deletion workflows

Agent permission inheritance

Agents cannot automatically expand their own permissions.

---

# 36. Privacy and Collection Controls

DDU should implement explicit collection boundaries.

Every connector should define:

* Supported data sources
* Access requirements
* Collection permissions
* Rate limits
* Retention policy
* Investigation scope

The system should maintain separation between:

Publicly discoverable data

User-provided data

Authenticated data

Restricted data

Agents should only access data permitted within the active investigation context.

---

# 37. Product Differentiation

DDU is not:

An object detector.

A username search tool.

A geolocation model.

An OSINT scanner.

A graph database.

A web scraper.

The product is the integration of:

**Multimodal Perception**

*

**OSINT Discovery**

*

**Automated Enrichment**

*

**Multimodal Entity Resolution**

*

**Vector Intelligence**

*

**Ontology**

*

**Temporal Knowledge**

*

**Evidence Provenance**

*

**Confidence-Aware Reasoning**

*

**Agentic Investigation**

*

**Human Investigation Workspace**

The individual open-source projects provide capabilities.

DDU provides the intelligence lifecycle connecting them.

---

# 38. Core Proprietary Layer

The strongest proprietary component should be:

## DDU Intelligence Correlation Engine

It answers:

> Are these clues actually connected?

Inputs:

Visual similarity

Semantic similarity

Structured record similarity

Username similarity

Geographic compatibility

Temporal compatibility

Graph relationships

Source reliability

Independent corroboration

Contradicting evidence

Output:

Candidate relationship

*

Confidence

*

Evidence paths

Example:

```text
Account_17
        │
        │ POSSIBLY_BELONGS_TO
        │ Confidence: 78%
        ▼
Person_4

Evidence:
├── Username similarity
├── Shared geographic pattern
├── Visually similar media
└── Shared linked domain

Contradiction:
└── Different stated age
```

The investigator can inspect every supporting and contradicting path.

This is the core difference between DDU and a collection of disconnected OSINT tools.

---

# 39. Recommended Internal Service Architecture

DDU should be modular.

Recommended services:

**ddu-api**

Main application API.

**ddu-ingest**

File and URL ingestion.

**ddu-vision**

Grounded SAM 2 and MMDetection.

**ddu-ocr**

PaddleOCR.

**ddu-audio**

Whisper.

**ddu-geo**

GeoCLIP.

**ddu-discovery**

Sherlock.

**ddu-osint**

SpiderFoot integration.

**ddu-collector**

gallery-dl and future collectors.

**ddu-resolution**

Splink and multimodal entity resolution.

**ddu-vector**

Qdrant.

**ddu-ontology**

OpenSPG.

**ddu-temporal**

Graphiti.

**ddu-lineage**

OpenLineage integration.

**ddu-agent**

LangGraph workflows.

**ddu-ui**

Cytoscape.js + MapLibre + Timeline.

---

# 40. Product Identity

## DDU

**Digital Detective Unit**

Primary product line:

> **Start with one clue.**

Alternative descriptor:

> **Multimodal Investigation and Intelligence Platform**

The branding should feel like an operational system rather than a consumer AI assistant.

The interface should communicate:

Precision

Evidence

Control

Correlation

Investigation

The system should visually emphasize the distinction between:

Observed

Inferred

Confirmed

Contradicted

This distinction should become part of the DDU visual language.

---

# 41. Success Criteria

DDU succeeds when an investigator can:

1. Start with a single clue.
2. Automatically extract relevant information.
3. Discover related public entities.
4. Analyze images, video, audio, and documents.
5. Identify possible geographic context.
6. Correlate observations across sources.
7. Resolve candidate identities probabilistically.
8. Explore relationships through a graph.
9. Explore observations geographically.
10. Understand changes over time.
11. Trace every conclusion to evidence.
12. Identify contradictory evidence.
13. Automate repetitive investigation steps.
14. Maintain human control over uncertain conclusions.

The target experience is:

> **One clue enters DDU. An evidence-backed intelligence graph emerges.**
