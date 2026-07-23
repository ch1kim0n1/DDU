# DDU Post-MVP Features

## Purpose

This document captures high-impact post-MVP capabilities that extend DDU from a multimodal investigation platform into a deeper temporal, relational, geospatial, and public-record intelligence system.

The features are organized by capability impact and operational risk. The goal is to make prioritization explicit while preserving the existing DDU principles of provenance, confidence, contradiction handling, human review, and evidence-backed reasoning.

---

# Tier Summary

| Tier | Capability | Capability Impact | Risk Level | Primary Value |
|---|---|---:|---:|---|
| S | Real-Time / Near-Real-Time Location Inference | Extreme | 10/10 | Current-location hypothesis generation |
| S | Relatives / Household Graph | Extreme | 10/10 | Family and household relationship discovery |
| S | Property / Housing / Public Tax Record Resolution | Extreme | 10/10 | Physical-location and ownership enrichment |
| S | Automated Cross-Platform Identity Resolution | Extreme | 10/10 | Connect fragmented identities across services |
| S | Pattern-of-Life Modeling | Extreme | 10/10 | Infer routines and recurring locations |
| S | Temporal Intelligence Engine | Extreme | 10/10 | Continuously detect changes in an investigation graph |
| A | Social-Circle Expansion | Very High | 9.5/10 | Discover close associates and secondary identities |
| A | Historical Location Reconstruction | Very High | 9.5/10 | Reconstruct movement history from public evidence |
| A | Alias / Identity-History Engine | Very High | 9.5/10 | Recover past usernames and identity transitions |
| A | Public-Record Fusion | Very High | 9.5/10 | Merge records from multiple public databases |
| A | Relationship-Strength Scoring | High | 9/10 | Estimate likely relationship type and strength |
| A | Life-Event Inference | High | 9/10 | Detect moves, job changes, relationships, and other transitions |
| B | Employment / Organization Graph | High | 8.5/10 | Map professional and organizational ties |
| B | Vehicle / Asset Association | High | 8.5/10 | Link recurring public assets to entities |
| B | Deleted-Content / Web-History Preservation | High | 8.5/10 | Preserve removed or changed public evidence |
| B | Location Confidence Fusion | High | 8/10 | Combine multiple weak geolocation signals |
| C | 3D Investigation Graph / Digital Scene | Medium | 5/10 danger, 9/10 UX | Improve investigation visualization |

---

# S-Tier Features

## 1. Real-Time / Near-Real-Time Location Inference

### Goal

Generate ranked current-location hypotheses from fresh public signals rather than only reconstructing historical location.

### Potential Inputs

- Recently published public posts
- Public event attendance
- Geotagged public media
- Publicly visible landmarks
- OCR from signs, storefronts, transit, or venue names
- Weather and lighting consistency
- Time-zone and posting-time patterns
- Publicly available live-event or venue information
- Recurring-location history

### Outputs

- Candidate current locations
- Confidence score per location
- Evidence path supporting each hypothesis
- Timestamp freshness
- Contradicting evidence
- Geographic uncertainty radius

### DDU Integration

```text
Fresh Evidence
    ↓
Temporal Intelligence Engine
    ↓
Geospatial Analyst
    ↓
Location Confidence Fusion
    ↓
Candidate Current Locations
    ↓
Contradiction Engine
    ↓
Human Review
```

### Risk

**10/10**

This is one of the strongest capability escalations because it moves DDU from retrospective OSINT toward actionable present-time tracking.

---

## 2. Relatives / Household Graph

### Goal

Discover and model possible family, household, and close personal relationships around an investigated entity.

### Potential Relationship Types

- Parents
- Children
- Siblings
- Spouses / partners
- Extended family
- Roommates
- Household members
- Long-term co-residents

### Potential Evidence Sources

- Public profiles
- Public records
- Shared addresses
- Public property records
- Public obituaries
- Public wedding announcements
- Public organization or school records
- Publicly disclosed family relationships
- Graph overlap across multiple independent sources

### Graph Model

```text
Person
├── Parent
├── Parent
├── Sibling
├── Partner
├── Child
├── Household
└── Associated Address
```

Every relationship should include:

- source
- provenance
- confidence
- verification state
- first observed
- last observed
- contradictory evidence

### Risk

**10/10**

This dramatically expands the investigation surface because related people become alternate paths to identify, locate, or contextualize a target.

---

## 3. Property / Housing / Public Tax Record Resolution

### Goal

Enrich an entity using legally accessible public property, housing, and tax-related records.

### Potential Sources

- County property assessor records
- Property tax records
- Deed records
- Parcel databases
- Public ownership records
- Mailing-address records
- Public corporate ownership records
- Historical ownership changes

### Capabilities

- Person → candidate property
- Address → owner
- Address → historical owners
- Owner → other properties
- Property → associated entities
- Parcel → geographic map placement
- Ownership timeline

### DDU Graph Example

```text
Person
  ↓ possible_owner
Property
  ↓ parcel
Geographic Location
  ↓ mailing_address
Associated Address
  ↓ shared_with
Other Entities
```

### Risk

**10/10**

The capability can bridge online identity information into physical-world location and ownership context.

---

## 4. Automated Cross-Platform Identity Resolution

### Goal

Determine whether accounts, profiles, images, and records from different platforms likely refer to the same entity.

### Signals

- Username similarity
- Historical usernames
- Display-name similarity
- Face similarity
- Profile-photo similarity
- Image reuse
- Bio similarity
- Writing-style similarity
- Shared URLs
- Shared email patterns
- Geographic overlap
- Temporal overlap
- Employment overlap
- Social-graph overlap
- Public media similarity

### Architecture

```text
Candidate Accounts
    ↓
Feature Extraction
    ↓
Multimodal Entity Resolver
    ↓
Correlation Engine
    ↓
Independent Corroboration
    ↓
Contradiction Search
    ↓
Identity-Link Probability
```

### Risk

**10/10**

This is the central capability that allows a weak clue to propagate through multiple platforms and data sources.

---

## 5. Pattern-of-Life Modeling

### Goal

Infer recurring behavior and routine from historical public evidence.

### Possible Patterns

- Likely workplace
- Likely residence area
- School or university
- Gym or recurring venue
- Common travel corridor
- Frequently visited businesses
- Weekend patterns
- Regular event attendance
- Time-zone behavior

### Model

```text
Observation
    ↓
Time + Location
    ↓
Recurring Cluster Detection
    ↓
Temporal Consistency
    ↓
Pattern Hypothesis
    ↓
Confidence + Contradiction Review
```

### Risk

**10/10**

Pattern-of-life analysis can make fragmented historical observations operationally meaningful.

---

## 6. Temporal Intelligence Engine

### Goal

Turn the DDU graph from a static investigation artifact into a continuously evolving temporal intelligence model.

### Responsibilities

- Detect newly observed entities
- Detect relationship changes
- Detect username changes
- Detect profile changes
- Detect new public locations
- Detect removed or changed public content
- Detect employment changes
- Detect new organizations
- Detect newly connected associates
- Detect contradictory timeline events

### Core Question

> What changed since the last investigation state?

### Architecture

```text
Previous Investigation Graph
    +
New Evidence
    ↓
Temporal Diff Engine
    ↓
Change Detection
    ↓
Significance Scoring
    ↓
Hypothesis Update
    ↓
Investigation Re-Planning
```

### Suggested Entity Properties

- first_seen
- last_seen
- valid_from
- valid_to
- observed_at
- superseded_by
- confidence_history

### Risk

**10/10**

This is the capability that can turn DDU from a one-time investigation platform into a persistent monitoring system.

---

# A-Tier Features

## 7. Social-Circle Expansion

### Goal

Identify and rank important relationships around an entity.

### Inputs

- Public follower/following relationships
- Public interactions
- Repeated co-appearance in media
- Shared organizations
- Shared locations
- Mentions and tags
- Public event co-attendance
- Mutual connections

### Outputs

- Candidate close associates
- Relationship confidence
- Relationship type hypothesis
- Interaction frequency
- Temporal persistence

### Risk

**9.5/10**

Social-circle expansion creates secondary investigation paths through friends, coworkers, partners, and organizations.

---

## 8. Historical Location Reconstruction

### Goal

Build a chronological map of where an entity was likely present over time.

### Inputs

- Geotagged public media
- EXIF data when publicly available
- Image geolocation
- OCR
- Landmarks
- Event attendance
- Public check-ins
- Archived profiles
- Public posts

### Output

```text
Timeline
├── 2024-06 → Austin, TX — high confidence
├── 2024-08 → Dallas, TX — medium confidence
├── 2024-12 → San Francisco, CA — high confidence
└── 2025-01 → Unknown — conflicting evidence
```

### Risk

**9.5/10**

---

## 9. Alias / Identity-History Engine

### Goal

Track identity changes over time.

### Capabilities

- Previous usernames
- Previous display names
- Historical bios
- Historical domains
- Historical profile URLs
- Email-pattern changes
- Account migrations
- Reused profile images

### DDU Integration

```text
Current Identity
    ↓
Historical Alias Search
    ↓
Archived Evidence
    ↓
Temporal Entity Resolution
    ↓
Identity Timeline
```

### Risk

**9.5/10**

This can reconnect identities that were intentionally separated over time.

---

## 10. Public-Record Fusion Engine

### Goal

Normalize and correlate multiple categories of legally accessible public records.

### Candidate Record Types

- Property records
- Corporate registrations
- Professional licenses
- Public court indexes
- Campaign contribution records
- Public permits
- Organization records
- Public business filings

### Core Requirement

Every source must carry:

- jurisdiction
- collection time
- source URL
- record identifier
- reliability
- entity-match confidence

### Risk

**9.5/10**

---

## 11. Relationship-Strength Scoring

### Goal

Estimate not only whether two entities are connected, but the probable nature and strength of that connection.

### Signals

- Interaction frequency
- Interaction duration
- Co-location frequency
- Shared organizations
- Mutual connections
- Repeated public mentions
- Household overlap
- Temporal persistence

### Example Output

```text
Entity A ↔ Entity B
Relationship hypothesis: coworker
Confidence: 0.82
Strength: medium-high
First observed: 2022
Last observed: 2026
Supporting evidence: 7 independent observations
Contradictions: 1
```

### Risk

**9/10**

---

## 12. Life-Event Inference

### Goal

Detect probable major changes in an entity's life or circumstances.

### Potential Events

- Relocation
- Job change
- Employer departure
- New organization affiliation
- Graduation
- Relationship change
- Business formation
- Extended travel

### Architecture

```text
Temporal Graph Changes
    ↓
Event Pattern Detection
    ↓
Candidate Life Event
    ↓
Supporting Evidence Search
    ↓
Contradiction Search
    ↓
Confidence Estimate
```

### Risk

**9/10**

---

# B-Tier Features

## 13. Employment / Organization Graph

### Goal

Map an entity's professional and organizational network.

### Nodes

- Employers
- Previous employers
- Teams
- Universities
- Research groups
- Conferences
- Professional associations
- Open-source organizations
- Companies

### Relationships

- works_at
- worked_at
- studied_at
- collaborated_with
- contributed_to
- attended
- member_of

### Risk

**8.5/10**

---

## 14. Vehicle / Asset Association

### Goal

Associate recurring publicly visible assets with candidate entities when supported by evidence.

### Possible Assets

- Vehicles
- Boats
- Publicly visible equipment
- Recurring devices or objects
- Public business assets

### Important Constraint

Asset association should remain probabilistic and evidence-backed. A recurring object in imagery must not automatically be treated as ownership.

### Risk

**8.5/10**

---

## 15. Deleted-Content / Web-History Preservation

### Goal

Preserve public evidence over time and detect when it disappears or changes.

### Capabilities

- Page snapshots
- DOM snapshots
- Screenshots
- Archived public profiles
- Changed bios
- Changed usernames
- Removed posts where historical public captures exist
- Website diffs

### DDU Integration

```text
Public Source
    ↓
Browsertrix Capture
    ↓
Evidence Store
    ↓
Temporal Diff
    ↓
Change Event
```

### Risk

**8.5/10**

---

## 16. Location Confidence Fusion

### Goal

Combine multiple weak location signals into one ranked location hypothesis.

### Inputs

- GeoCLIP
- OCR
- Landmarks
- Architecture
- Terrain
- Vegetation
- Weather consistency
- Shadows / time-of-day consistency
- Business names
- Transit infrastructure
- Road signs
- Language
- Temporal evidence

### Output

```text
Candidate Location: Austin, TX
Confidence: 0.86

Evidence:
+ OCR detected "Austin"
+ GeoCLIP ranked Central Texas
+ Architecture consistent
+ Weather observation consistent

Contradictions:
- One visual feature resembles Phoenix
```

### Risk

**8/10**

---

# C-Tier Features

## 17. 3D Investigation Graph / Digital Scene

### Goal

Create a more immersive and spatial representation of investigation data.

### Concept

Rather than rendering only a traditional node-link graph, DDU can provide a 3D investigation space where entities, locations, timelines, evidence, and relationships are visually organized.

### Possible Views

#### 3D Entity Graph

- Person nodes
- Account nodes
- Organization nodes
- Location nodes
- Evidence nodes

#### Geographic Scene

- Map terrain
- Properties
- Investigation locations
- Movement timelines

#### Time-Space View

```text
X-axis = time
Y-axis = relationship distance
Z-axis = confidence / evidence depth
```

#### Investigation Playback

Allow an investigator to replay how the graph evolved:

```text
Seed
↓
First account discovered
↓
Second identity linked
↓
Location inferred
↓
Public record discovered
↓
Relationship confirmed
```

### Visual Effects

- New evidence pulses into the graph
- Confidence changes animate relationship thickness
- Contradictions render as competing edges
- Evidence lineage can be expanded visually
- Temporal changes appear as graph diffs
- Investigation branches visibly grow in real time

### Risk

**5/10 direct danger**

**9/10 UX impact**

The visualization itself adds relatively little investigative capability but can make complex intelligence substantially easier to understand and act upon.

---

# Combined Post-MVP Capability Model

The full post-MVP architecture could evolve toward:

```text
Initial Clue
    ↓
Multimodal Identity Resolution
    ↓
Cross-Platform Accounts
    ↓
Alias History
    ↓
Relatives / Household
    ↓
Social Circle
    ↓
Employment / Organizations
    ↓
Public Records
    ↓
Property / Housing
    ↓
Historical Location Reconstruction
    ↓
Pattern-of-Life Modeling
    ↓
Temporal Intelligence
    ↓
New Evidence Detection
    ↓
Hypothesis Update
    ↓
Investigation Re-Planning
```

The major architectural transition is:

```text
MVP DDU
One clue → evidence-backed investigation graph

Post-MVP DDU
One clue → evolving multimodal identity and relationship intelligence model
```

---

# Recommended Post-MVP Build Order

## Phase 1 — Identity Depth

1. Automated Cross-Platform Identity Resolution
2. Alias / Identity-History Engine
3. Social-Circle Expansion
4. Relationship-Strength Scoring

## Phase 2 — Public-Record Intelligence

5. Public-Record Fusion Engine
6. Property / Housing / Public Tax Record Resolution
7. Relatives / Household Graph
8. Employment / Organization Graph

## Phase 3 — Geospatial and Temporal Intelligence

9. Historical Location Reconstruction
10. Location Confidence Fusion
11. Pattern-of-Life Modeling
12. Life-Event Inference

## Phase 4 — Persistent Intelligence

13. Temporal Intelligence Engine
14. Deleted-Content / Web-History Preservation
15. Change Detection and Investigation Re-Planning

## Phase 5 — Advanced Visualization

16. 3D Investigation Graph
17. Geographic Scene View
18. Time-Space Intelligence View
19. Investigation Playback

---

# Required Safety and Governance Architecture

These post-MVP features materially increase DDU's ability to correlate public information about real people. They should therefore be paired with platform-level controls rather than implemented as unrestricted tools.

## Investigation Authorization

Every investigation should record:

- investigation purpose
- operator identity
- authorized scope
- permitted data sources
- permitted tools
- retention policy

## High-Risk Capability Gates

Capabilities such as:

- current-location inference
- household relationship discovery
- precise residential-location resolution
- face-to-identity linkage
- pattern-of-life analysis

should require explicit authorization and review.

## Immutable Audit Trail

Record:

- who performed an action
- what was searched
- when it occurred
- which tool was used
- what evidence was accessed
- what data was exported

## Confidence and Provenance

No inferred relationship should silently become fact.

Every result must retain DDU's existing distinction between:

- Observation
- Claim
- Inference
- Hypothesis
- Verified Fact
- Contradiction

## Investigation Scope Controls

Prevent unrestricted expansion from one subject into arbitrary large-scale person discovery without explicit authorization.

## Export Controls

Bulk export of identity graphs, household graphs, or location histories should be governed separately from interactive investigation access.

---

# Final Product Direction

The strongest post-MVP version of DDU is not simply a larger collection of OSINT tools.

It is a temporal intelligence system that can:

1. Start from a weak clue.
2. Resolve candidate identities.
3. Connect accounts across platforms.
4. Recover identity history.
5. Map relationships and organizations.
6. Enrich entities with public records.
7. Build geographic and temporal hypotheses.
8. Detect contradictions.
9. Observe how the intelligence graph changes over time.
10. Re-plan investigations as new evidence appears.

The defining post-MVP capability is the **Temporal Intelligence Engine** combined with the existing **DDU Intelligence Correlation Engine**.

Together they change the core question from:

> Are these clues connected?

into:

> Are these clues connected, how has that connection changed over time, and what new evidence is most valuable to investigate next?
