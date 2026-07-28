# DDU

## Digital Detective Unit

### Product Development Document

### Product, AI, Data, Visualization, and Investigation Architecture

**Product Name:** DDU
**Full Name:** Digital Detective Unit
**Category:** Multimodal Investigation, OSINT, Knowledge Graph, and AI Intelligence Platform
**Architecture:** Open-source-first, ontology-native, evidence-backed, hypothesis-driven
**Primary Interaction Model:** AI Detective + Living Investigation Graph
**Core Principle:** Every conclusion must be traceable to evidence, uncertainty, provenance, and time.

---

# 1. Executive Summary

DDU is an AI-native multimodal investigation platform that transforms fragmented digital evidence and public information into a continuously evolving intelligence graph.

A user begins with one or more investigative seeds:

* Username
* Image
* Video
* Audio
* URL
* Web page
* Public profile
* Document
* Domain
* Organization
* Location
* Known clue

DDU's AI Detective then:

1. Establishes the investigation goal.
2. Builds competing hypotheses.
3. Identifies missing information.
4. Determines which investigative action has the highest expected value.
5. Calls specialized tools.
6. Preserves evidence.
7. Extracts observations.
8. Correlates entities across modalities.
9. Searches for supporting and contradicting evidence.
10. Updates confidence in hypotheses.
11. Expands promising investigative branches.
12. Stops when additional investigation has insufficient value or reaches policy limits.

The investigation unfolds visually in real time.

The user does not wait for a spinner.

They watch:

* Entities appear.
* Relationships form.
* Accounts connect.
* Locations emerge.
* Evidence accumulate.
* Hypotheses strengthen or weaken.
* Contradictions surface.
* Investigation branches expand.

DDU combines autonomous investigative reasoning with a human-controlled intelligence workspace.

The core product experience is:

> Start with one clue.
> Watch DDU investigate it.
> Understand every connection.

---

# 2. Product Vision

DDU should become an AI investigation operating system.

Its purpose is not simply to search.

Its purpose is to reason about:

**What is known?**

**What might be true?**

**What evidence supports it?**

**What evidence contradicts it?**

**What information is missing?**

**What investigative action would reduce uncertainty the most?**

The primary lifecycle is:

**Acquire → Preserve → Observe → Hypothesize → Investigate → Correlate → Challenge → Verify → Learn**

The final system should behave less like an AI search engine and more like a disciplined investigative team.

---

# 3. Product Thesis

Traditional OSINT systems typically operate as collections of tools.

A user decides:

* what to search,
* which tool to use,
* which result matters,
* what should be investigated next.

DDU moves this reasoning into the platform.

Instead of:

> User → Tool → Result

DDU operates as:

> User → Investigation Goal → Hypotheses → Evidence Gaps → Best Next Action → Tool → Evidence → Belief Update → Re-plan

The product's value comes from its ability to determine:

> What should I investigate next, and why?

---

# 4. Core Intelligence Model

DDU separates knowledge into six distinct categories.

## Observation

Something directly extracted or detected.

Example:

PaddleOCR detected the word "Austin."

---

## Claim

Something asserted by an external source.

Example:

A public profile states that the account holder lives in Austin.

---

## Inference

A machine-generated conclusion.

Example:

GeoCLIP predicts Central Texas as the probable image location.

---

## Hypothesis

A proposition DDU is investigating.

Example:

Account_A and Account_B may belong to the same person.

---

## Verified Fact

A conclusion meeting a defined verification standard.

Example:

A photograph contains GPS metadata corresponding to Austin.

---

## Contradiction

Evidence incompatible with another claim or hypothesis.

Example:

Two supposedly identical entities appear in geographically incompatible locations at the same time.

These categories must remain visually and logically separate.

---

# 5. Open-Source Technology Foundation

DDU uses replaceable open-source capabilities behind standardized adapters.

## GeoCLIP

Role:

Visual geolocation.

Usage:

Image → candidate geographic locations.

---

## SpiderFoot

Role:

OSINT enrichment.

Usage:

Domains, infrastructure, public identifiers, external intelligence sources.

---

## Sherlock

Role:

Username-based account discovery.

Usage:

Username → candidate public accounts.

---

## gallery-dl

Role:

Public media acquisition.

Usage:

Supported profile/media URL → media evidence.

---

## Browsertrix Crawler

Role:

Evidence-grade web preservation.

Usage:

URL → replayable web capture + page evidence.

---

## Grounded SAM 2

Role:

Open-vocabulary image/video detection and tracking.

---

## MMDetection

Role:

Specialized and domain-trained object detection.

---

## PaddleOCR

Role:

Scene text and document OCR.

---

## Whisper

Role:

Audio/video transcription.

---

## CompreFace

Role:

Face similarity and candidate face matching.

---

## Splink

Role:

Structured probabilistic entity resolution.

---

## Qdrant

Role:

Vector similarity search.

---

## OpenSPG

Role:

Canonical ontology.

---

## Graphiti

Role:

Temporal evolving knowledge.

---

## Neo4j

Role:

Persistent graph storage and traversal.

---

## OpenLineage

Role:

Processing provenance and lineage.

---

## LangGraph

Role:

Agent workflow and investigation orchestration.

---

## Cytoscape.js

Role:

Interactive network visualization.

---

## MapLibre GL JS

Role:

Geospatial visualization.

---

## S3-Compatible Object Store

Role:

Raw and derived evidence storage.

---

# 6. DDU Core Proprietary Systems

The open-source projects provide capabilities.

DDU owns the intelligence between them.

## DDU Hypothesis Engine

Maintains competing explanations.

---

## DDU Intelligence Correlation Engine

Determines whether clues are related.

---

## DDU Belief Engine

Updates confidence as new evidence arrives.

---

## DDU Contradiction Engine

Actively searches for evidence against current conclusions.

---

## DDU Value-of-Information Engine

Determines the most useful next investigative action.

---

## DDU Multimodal Entity Resolver

Connects identities and objects across different modalities.

---

## DDU Evidence Dependency Graph

Tracks how every conclusion depends on underlying evidence.

---

## DDU Investigation Strategy Learner

Learns which investigative workflows produce valuable results.

---

## DDU Interview Intelligence Engine

Extracts additional voluntary recollections from the user through non-leading investigative questioning.

---

# 7. AI Detective Architecture

The AI Detective is the primary intelligence layer.

It is not a chatbot with tool access.

It operates as an investigation manager.

```text
User
  │
  ▼
Lead AI Detective
  │
  ▼
Investigation Goal
  │
  ▼
Hypothesis Engine
  │
  ├── Hypothesis A
  ├── Hypothesis B
  └── Hypothesis C
  │
  ▼
Evidence Gap Analysis
  │
  ▼
Value-of-Information Engine
  │
  ▼
Best Next Action
  │
  ▼
Specialist Agent / Tool
  │
  ▼
Evidence
  │
  ▼
Correlation
  │
  ▼
Belief Update
  │
  ▼
Contradiction Search
  │
  ▼
Re-plan
```

---

# 8. Specialist AI Detective Team

DDU should use specialized investigative agents.

## Lead Investigator

Responsibilities:

* Maintain investigation objective.
* Prioritize hypotheses.
* Assign investigative tasks.
* Determine when to stop.

---

## Identity Analyst

Responsibilities:

* Usernames.
* Accounts.
* Person/account linkage.
* Splink entity resolution.
* Face and profile similarity.

---

## Visual Intelligence Analyst

Responsibilities:

* Images.
* Video.
* Object tracking.
* Visual similarity.
* Object identity.

---

## Geospatial Analyst

Responsibilities:

* GeoCLIP.
* Location clues.
* Geographic consistency.
* Map-based reasoning.

---

## Web and OSINT Analyst

Responsibilities:

* Sherlock.
* SpiderFoot.
* Browsertrix.
* gallery-dl.
* Public source discovery.

---

## Timeline Analyst

Responsibilities:

* Temporal ordering.
* Event reconstruction.
* Impossible travel.
* Overlapping observations.

---

## Graph Analyst

Responsibilities:

* Neo4j traversal.
* Cluster detection.
* Hidden bridges.
* Relationship patterns.

---

## Evidence Auditor

Responsibilities:

* Provenance.
* Source reliability.
* Independent corroboration.
* Evidence dependency.

---

## Skeptic Agent

Responsibilities:

Actively attempt to disprove important hypotheses.

The Skeptic Agent should ask:

> What evidence would make this conclusion wrong?

---

# 9. Hypothesis-Driven Investigation

DDU investigations revolve around hypotheses.

Example:

Seed:

username `example123`

Hypothesis A:

Multiple discovered accounts belong to the same person.

Hypothesis B:

The username is reused by unrelated people.

Hypothesis C:

Some accounts belong to the same person while others do not.

DDU maintains evidence for and against each.

The goal is not to confirm the first theory.

The goal is to discriminate between plausible explanations.

---

# 10. Value-of-Information Engine

For every possible action, calculate an Investigation Priority Score.

Inputs:

* Expected information gain.
* Hypothesis relevance.
* Cost.
* Latency.
* Tool reliability.
* Investigation depth.
* Privacy/access constraints.
* Redundancy.

Conceptually:

```text
Priority =
Expected Information Gain
× Relevance
× Reliability
÷ Cost
÷ Redundancy
```

Example:

Run Sherlock:

High information value.

Low cost.

Run GeoCLIP on a key photograph:

High information value.

Low cost.

Download thousands of unrelated images:

Low marginal information value.

High cost.

DDU prioritizes the highest-value action.

---

# 11. Investigation Frontier

DDU treats investigations as intelligent graph search.

Maintain:

* Investigated Nodes.
* Frontier Nodes.
* High-Priority Leads.
* Low-Priority Leads.
* Blocked Leads.
* Rejected Leads.

Every frontier node receives a priority.

The AI Detective investigates high-value nodes first.

This prevents uncontrolled recursive expansion.

---

# 12. Active Contradiction Search

Every important hypothesis should trigger an adversarial investigation.

Example:

Hypothesis:

Account_A and Account_B belong to the same person.

DDU searches for:

* Conflicting age.
* Conflicting gender information.
* Impossible location overlap.
* Contradictory employment history.
* Incompatible timestamps.
* Different linked identities.

The system should reward disconfirmation.

---

# 13. Belief Updating

Confidence should evolve.

Example:

```text
Account A = Person X

Initial probability: 0.20

Exact username:
0.48

Shared domain:
0.67

Similar profile imagery:
0.82

Geographic overlap:
0.90

Contradictory stated age:
0.71
```

Confidence history must remain visible.

---

# 14. Source Independence

DDU must identify whether multiple pieces of evidence originate from the same source.

Example:

Source A publishes claim.

Source B copies A.

Source C quotes B.

The system should not count this as three independent confirmations.

DDU should maintain:

Evidence Origin

↓

Derived Sources

↓

Dependent Claims

---

# 15. Evidence Dependency Graph

Every conclusion should have dependencies.

```text
Hypothesis
   │
   ├── Relationship A
   │      └── Observation A
   │             └── Image Evidence
   │
   ├── Relationship B
   │      └── Web Capture
   │
   └── Contradiction C
          └── Document Evidence
```

If evidence is invalidated:

DDU automatically identifies affected downstream conclusions.

Example:

Evidence_22 marked unreliable.

DDU recalculates:

* 4 relationships.
* 2 hypotheses.
* 1 entity merge.

---

# 16. Temporal-Spatial Consistency Engine

DDU should reason about:

**Who + What + Where + When**

Example:

Entity_A observed:

Austin

14:00

Entity_A observed:

New York

14:30

DDU generates:

Temporal-Geographic Contradiction.

This applies to:

* People.
* Vehicles.
* Devices.
* Accounts.
* Events.

---

# 17. Cross-Modal Object Identity

DDU should resolve physical objects across evidence.

Example:

Vehicle Observation A.

Vehicle Observation B.

Similarity signals:

* Visual embedding.
* Make.
* Model.
* Color.
* Plate OCR.
* Damage pattern.
* Geographic compatibility.
* Temporal compatibility.

Output:

Vehicle_A

POSSIBLY_SAME_AS

Vehicle_B

Confidence:

0.83

Apply similar logic to:

* Buildings.
* Clothing.
* Devices.
* Logos.
* Locations.
* Distinctive physical objects.

---

# 18. Investigation Memory

DDU should use three memory levels.

## Case Memory

Everything learned in one investigation.

---

## Entity Memory

Everything known about a specific entity.

---

## Method Memory

Historical performance of investigation strategies.

Example:

DDU learns:

Sherlock → Browsertrix → OCR → Domain Search

produces high-value results for a certain account pattern.

Future investigations prioritize that workflow.

---

# 19. Strategy Learning

Record every investigative action.

Fields:

Tool.

Context.

Cost.

Latency.

Entities discovered.

Verified relationships created.

False positives.

Information gain.

Over time DDU learns:

Which tools are useful for which situations?

This produces adaptive investigation policies.

---

# 20. AI Interview Intelligence

The user may know useful information that they have not initially provided.

DDU should ask structured, non-leading questions.

Example:

User:

I met this person at a party.

DDU:

> Tell me everything you remember about them.

User:

Tall, around my age, long hair.

DDU:

> What do you remember about their hair?

User:

Dark, maybe brown.

DDU stores:

Hair Length:

Long.

Confidence:

Medium.

Hair Color:

Dark/Brown.

Confidence:

Low to Medium.

Source:

User recollection.

---

# 21. Interview Intelligence Engine

Architecture:

```text
User Conversation
      │
      ▼
Recall Planner
      │
      ▼
Known Attributes
      │
      ▼
Missing High-Value Attributes
      │
      ▼
Question Value Scoring
      │
      ▼
Best Non-Leading Question
      │
      ▼
User Response
      │
      ▼
Attribute Extraction
      │
      ▼
Confidence / Uncertainty
      │
      ▼
Knowledge Graph
```

---

# 22. Interview Agent Components

## Recall Agent

Encourages broad free recall.

---

## Clarification Agent

Clarifies ambiguous statements.

---

## Gap Agent

Detects missing investigative attributes.

---

## Consistency Agent

Identifies inconsistencies.

---

## Contamination Guard

Prevents leading questions.

---

## Interview Strategist

Selects the highest-value next question.

---

# 23. Question Value Scoring

Do not ask questions merely because an attribute is missing.

Ask based on information value.

Example:

Candidate A:

Brown hair.

Rock climbing.

Austin.

Candidate B:

Blond hair.

Gaming.

Dallas.

DDU should independently ask:

> What do you remember about their hair?

Then:

> Did they ever mention activities they regularly did?

It should not reveal candidate answers first.

---

# 24. User Investigation Flow

## Step 1: Start Investigation

User selects:

New Investigation.

Inputs:

Username.

Image.

Video.

URL.

Document.

Domain.

Location.

Known description.

---

## Step 2: Investigation Goal

User describes objective.

Example:

> Identify which public accounts may belong to this person.

---

## Step 3: AI Detective Planning

DDU creates:

* Initial hypotheses.
* Known facts.
* Unknowns.
* Investigation branches.
* Tool plan.

---

## Step 4: User Knowledge Interview

If useful, DDU asks:

* Appearance.
* Context.
* Known username.
* Hobbies.
* Occupation.
* Location.
* Social context.

Questions are prioritized by expected information gain.

---

## Step 5: Autonomous Investigation

DDU begins calling tools.

The investigation graph appears immediately.

---

## Step 6: Real-Time Investigation

The user watches:

Searching.

Discovering.

Connecting.

Questioning.

Validating.

Rejecting.

---

## Step 7: User Steering

User can:

Investigate deeper.

Stop branch.

Verify relationship.

Reject relationship.

Add evidence.

Ask AI Detective a question.

---

## Step 8: Findings

DDU generates:

* Primary findings.
* Competing hypotheses.
* Confidence.
* Supporting evidence.
* Contradictions.
* Unresolved questions.

---

# 25. Real-Time Visualization Philosophy

The user should never feel:

> The system is processing.

The user should feel:

> The investigation is unfolding.

The visualization system should communicate:

**Searching → Discovering → Connecting → Testing → Validating**

---

# 26. Living Investigation Graph

Cytoscape.js powers the main visual workspace.

Nodes should animate into the graph as they are discovered.

Examples:

Username node appears.

↓

Account nodes expand.

↓

Profile images appear.

↓

Domain node connects.

↓

Location hypothesis appears.

↓

Organization cluster forms.

Graph layout should update smoothly rather than reload.

---

# 27. Progressive Graph Reveal

Do not display every node immediately.

Use semantic levels.

## Level 1

Strong direct relationships.

## Level 2

Relevant second-order relationships.

## Level 3

Full graph.

Users can expand branches manually.

The AI Detective can automatically expand high-priority frontier nodes.

---

# 28. Visual Entity Language

Each entity should have a distinct visual form.

Person:

Portrait or circular node.

Account:

Platform icon.

Location:

Map pin.

Vehicle:

Object card.

Image:

Thumbnail.

Video:

Thumbnail with play indicator.

Organization:

Organization node.

Domain:

Globe/network node.

Evidence:

Document/media card.

Hypothesis:

Diamond.

Contradiction:

Conflict indicator.

---

# 29. Relationship Visual Language

Verified:

Solid edge.

Candidate:

Dashed edge.

Weak hypothesis:

Faint edge.

Strong relationship:

Thicker edge.

Contradiction:

Double or broken conflict edge.

Historical:

Dimmed edge.

Confidence should also influence visual intensity.

---

# 30. Detective Activity Stream

Persistent side panel.

Example:

```text
21:01:14
Checking username across public platforms.

21:01:19
12 candidate accounts discovered.

21:01:28
3 profiles share similar imagery.

21:01:44
New geographic evidence detected.

21:01:51
Location hypothesis:
Austin, Texas
Confidence increased from 58% to 74%.

21:02:10
Contradiction detected:
Two profiles report incompatible ages.
```

This gives continuous visible progress.

---

# 31. Investigation Branches

Display active reasoning branches.

Example:

Identity

Status:

Strong Lead.

Geolocation

Status:

Exploring.

Organization

Status:

Weak Lead.

Vehicle

Status:

Blocked.

User can select:

Investigate Deeper.

Pause.

Stop.

---

# 32. New Lead Events

High-value discoveries should produce subtle visual focus.

Example:

NEW LEAD

Shared external domain detected across three accounts.

Relevant graph nodes highlight.

Camera shifts toward the cluster.

The animation should be restrained.

DDU should feel sophisticated, not gamified.

---

# 33. Evidence Thumbnails

Evidence nodes should show real visual content where possible.

Examples:

Profile photo.

Captured page.

Vehicle crop.

Image.

Document preview.

This makes the graph understandable without clicking every node.

---

# 34. Graph Constellations

Automatically group nodes into clusters.

Examples:

Identity Cluster.

Organization Cluster.

Account Cluster.

Location Cluster.

Event Cluster.

Media Cluster.

At distant zoom:

Show clusters.

At close zoom:

Reveal individual nodes.

---

# 35. Synchronized Analytical Views

The four primary views are:

## Graph

Relationships.

## Map

Geographic intelligence.

## Timeline

Temporal intelligence.

## Evidence

Source material.

All views remain synchronized.

Example:

Select Account_A.

Graph highlights relationships.

Map shows relevant locations.

Timeline displays activity.

Evidence shows related sources.

---

# 36. Map Visualization

MapLibre GL JS.

Location types must remain visually distinct.

Exact Observation.

Verified Location.

Approximate Location.

GeoCLIP Candidate.

Location Hypothesis.

Confidence Region.

Never display a predicted coordinate identically to a verified coordinate.

---

# 37. Timeline Visualization

Timeline shows:

Account discovery.

Media creation.

Evidence acquisition.

Observed events.

Entity movements.

Hypothesis changes.

Confidence changes.

Contradictions.

Selecting a period filters:

Graph.

Map.

Evidence.

---

# 38. Investigation Playback

DDU should record investigation progression.

Users can replay:

```text
00:00
Seed received.

00:08
Username accounts discovered.

00:17
Public profile captured.

00:29
Image analyzed.

00:41
Location hypothesis created.

01:04
Second account associated.

01:32
Contradiction discovered.
```

The graph reconstructs itself chronologically.

Use cases:

* Audit.
* Training.
* Presentation.
* Case review.
* Explainability.

---

# 39. Investigation HUD

Persistent compact summary.

Example:

Entities:

143

Evidence:

58

Active Hypotheses:

12

Contradictions:

4

Active Analysts:

3

High-Priority Leads:

7

This gives visible momentum.

---

# 40. Primary UI Layout

Recommended layout:

```text
┌────────────────────────────────────────────────────────┐
│ DDU / CASE-042                         Investigation HUD │
├────────────────┬───────────────────────────────────────┤
│ AI DETECTIVE   │                                       │
│                │                                       │
│ Activity       │          LIVE GRAPH                   │
│ Hypotheses     │                                       │
│ Findings       │                                       │
│ Branches       │                                       │
│ Questions      │                                       │
│                │                                       │
├────────────────┴──────────────────────────┬────────────┤
│ TIMELINE                                  │ EVIDENCE   │
├───────────────────────────────────────────┴────────────┤
│ MAP                                                    │
└────────────────────────────────────────────────────────┘
```

Alternative:

AI Detective remains persistent.

Main canvas switches between:

Graph.

Map.

Timeline.

Evidence.

---

# 41. Evidence Architecture

Every upper-level conclusion must be traceable downward.

```text
Hypothesis
   ↓
Relationship
   ↓
Entity
   ↓
Observation
   ↓
Evidence
```

This is the foundational DDU rule.

---

# 42. Canonical Evidence Model

Fields:

evidence_id

investigation_id

type

storage_uri

source_uri

sha256

mime_type

size

acquired_at

original_timestamp

acquisition_method

parent_evidence_id

verification_status

---

# 43. Evidence Types

IMAGE

VIDEO

AUDIO

DOCUMENT

WEB_CAPTURE

SCREENSHOT

PROFILE

POST

FRAME

OBJECT_CROP

FACE_CROP

---

# 44. Observation Model

Fields:

observation_id

type

value

confidence

source_evidence_id

tool

tool_version

model

model_version

observed_at

created_at

---

# 45. Entity Model

Entity types:

Person.

Account.

Username.

Organization.

Domain.

Location.

Vehicle.

Object.

Image.

Video.

Audio.

Document.

Post.

WebPage.

Event.

Source.

---

# 46. Relationship Model

Relationship types:

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

DISCOVERED_BY

Every relationship includes:

Confidence.

Evidence.

Contradictions.

Time.

Verification status.

Inference method.

---

# 47. Full Processing Architecture

```text
                          USER
                           │
                           ▼
                    LEAD AI DETECTIVE
                           │
                           ▼
                   HYPOTHESIS ENGINE
                           │
                           ▼
                 EVIDENCE GAP ANALYSIS
                           │
                           ▼
              VALUE-OF-INFORMATION PLANNER
                           │
                           ▼
                  SPECIALIST AI TEAM
                           │
                           ▼
                       TOOL LAYER
                           │
      ┌────────────────────┼─────────────────────┐
      ▼                    ▼                     ▼
  VISUAL TOOLS         OSINT TOOLS         WEB ACQUISITION
  SAM2                 Sherlock            Browsertrix
  MMDetection          SpiderFoot          gallery-dl
  PaddleOCR
  Whisper
  CompreFace
  GeoCLIP
                           │
                           ▼
                       EVIDENCE
                           │
                           ▼
                     OBSERVATIONS
                           │
                           ▼
                  ENTITY RESOLUTION
                  Splink + Qdrant
                           │
                           ▼
             DDU INTELLIGENCE CORRELATION
                           │
                           ▼
                 CONTRADICTION ENGINE
                           │
                           ▼
                    BELIEF ENGINE
                           │
                           ▼
                       OpenSPG
                           │
                           ▼
                       Graphiti
                           │
                           ▼
                        Neo4j
                           │
                           ▼
                    OpenLineage
                           │
                           ▼
                INVESTIGATION FRONTIER
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
              Continue           Stop
                  │
                  ▼
               Re-plan
```

---

# 48. Agent Runtime

LangGraph powers investigation state.

State:

investigation_id

goal

hypotheses

known_entities

evidence

contradictions

frontier

tool_budget

depth

permissions

open_questions

---

# 49. Agent Loop

```text
Assess Investigation
      ↓
Select Highest-Value Question
      ↓
Select Tool or User Question
      ↓
Execute
      ↓
Normalize Result
      ↓
Preserve Evidence
      ↓
Update Graph
      ↓
Update Hypotheses
      ↓
Search for Contradictions
      ↓
Evaluate Frontier
      ↓
Continue or Stop
```

---

# 50. Stop Conditions

Stop when:

No high-value unexplored leads remain.

Information gain falls below threshold.

Investigation budget exhausted.

Depth limit reached.

Tool limit reached.

Human approval required.

Scope boundary reached.

Repeated loop detected.

Investigation goal satisfied.

---

# 51. Tool Adapter Contract

Every external system implements a DDU adapter.

```text
ToolAdapter

name
version
supported_inputs
supported_outputs

health()
execute()
normalize()
```

Output:

```text
ToolResult

run_id
observations[]
entities[]
relationships[]
artifacts[]
confidence
errors[]
provenance
```

No external tool writes directly to the canonical graph.

---

# 52. Persistent Data Architecture

## Neo4j

Canonical relationship graph.

## Qdrant

Vector similarity.

## PostgreSQL

Application metadata.

## S3-Compatible Store

Evidence.

## Graphiti

Temporal intelligence.

## OpenSPG

Ontology.

---

# 53. Event Architecture

Queues:

vision

ocr

audio

geo

face

osint

web_capture

embedding

correlation

graph_update

belief_update

contradiction_scan

Events:

evidence.created

observation.created

entity.candidate.created

relationship.candidate.created

hypothesis.updated

contradiction.detected

lead.discovered

investigation.completed

---

# 54. Core Backend Services

ddu-api

ddu-ingest

ddu-evidence

ddu-web-capture

ddu-vision

ddu-ocr

ddu-audio

ddu-geo

ddu-face

ddu-discovery

ddu-osint

ddu-collector

ddu-resolution

ddu-correlation

ddu-hypothesis

ddu-belief

ddu-contradiction

ddu-frontier

ddu-interview

ddu-ontology

ddu-graph

ddu-vector

ddu-lineage

ddu-agent

---

# 55. Security Model

Required:

OIDC.

RBAC.

Investigation-level ACL.

Evidence permissions.

Audit logs.

Encryption.

Secret management.

Agent permission inheritance.

Retention controls.

All AI agents operate under the same permissions as the investigation context.

---

# 56. MVP

The MVP should prove the investigation loop.

Inputs:

Image.

Username.

URL.

User-provided description.

Core tools:

Grounded SAM 2.

PaddleOCR.

GeoCLIP.

Sherlock.

Browsertrix.

SpiderFoot.

Qdrant.

Neo4j.

Cytoscape.

MapLibre.

Core AI:

Lead AI Detective.

Hypothesis Engine.

Simple Value-of-Information Planner.

Correlation Engine.

Interview Gap Agent.

Contradiction Checker.

---

# 57. MVP Experience

User enters username.

DDU:

1. Creates hypotheses.
2. Asks useful missing questions.
3. Runs Sherlock.
4. Captures candidate profiles.
5. Extracts public media.
6. Analyzes images.
7. Generates location clues.
8. Resolves candidate accounts.
9. Builds graph.
10. Searches for contradictions.
11. Presents competing identity hypotheses.

All results appear in real time.

---

# 58. Development Phases

## Phase 0

Canonical data model.

Evidence storage.

Neo4j.

Qdrant.

PostgreSQL.

Events.

---

## Phase 1

Living Graph UI.

Image pipeline.

GeoCLIP.

OCR.

Visual objects.

---

## Phase 2

Sherlock.

SpiderFoot.

Browsertrix.

gallery-dl.

---

## Phase 3

Splink.

CompreFace.

Multimodal entity resolution.

Correlation Engine.

---

## Phase 4

Hypothesis Engine.

Belief Engine.

Contradiction Engine.

---

## Phase 5

Value-of-Information Planner.

Frontier management.

Specialist agent team.

---

## Phase 6

Interview Intelligence Engine.

Memory elicitation.

Gap analysis.

Non-leading question generation.

---

## Phase 7

Graphiti.

OpenSPG.

OpenLineage.

Investigation replay.

---

## Phase 8

Strategy learning.

Historical investigation performance.

Adaptive tool selection.

---

# 59. Core Differentiation

DDU is not:

An OSINT scraper.

An AI search engine.

A username finder.

A geolocation tool.

A graph visualization platform.

A face matching system.

DDU is:

> A hypothesis-driven autonomous investigation system that determines what evidence it needs, selects the highest-value investigative action, correlates multimodal clues, searches actively for contradictions, learns from previous investigations, and presents the entire process as a living evidence graph.

---

# 60. Product Moat

The moat is the combination of:

**Hypothesis-Driven Reasoning**

*

**Value-of-Information Planning**

*

**Multimodal Correlation**

*

**Active Contradiction Search**

*

**Probabilistic Belief Updating**

*

**Evidence Dependency Graph**

*

**Investigation Strategy Learning**

*

**Human Memory Elicitation**

*

**Real-Time Investigation Visualization**

The target experience is:

> The user provides one clue.
> DDU decides what it needs to know.
> DDU investigates.
> The user watches the intelligence picture form in real time.
> Every conclusion can be challenged and traced back to evidence.

**Start with one clue. Build the evidence graph.**
