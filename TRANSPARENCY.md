 # HASTE — High-speed Assessment and Satellite Tracking for Emergencies

**HASTE is an open-source, human-in-the-loop research workflow** developed by Microsoft's AI for Good Lab to support **rapid building-level damage assessment from post-disaster satellite and aerial imagery**. HASTE enables a trained operator to manually label small samples of post-event imagery, locally train an event-specific computer vision model, generate per-pixel damage predictions, and aggregate those predictions with external building-footprint datasets (e.g., OpenStreetMap, Overture Building Footprints) to produce building-level damage estimates. This documentation is intended to help stakeholders understand the purpose of the HASTE workflow and how it operates at a high level. This documentation applies to the open-source HASTE workflow as released through the `microsoft/haste` repository and to outputs distributed by Microsoft AI for Good Lab.

## Overview

The HASTE workflow takes post-disaster satellite or aerial imagery as input, applies a locally trained, event-specific computer vision model to identify visual indicators consistent with building damage, aggregates those per-pixel predictions against an external building-footprint dataset, and produces a building-level damage estimate (typically as a GeoPackage or similar geospatial artifact) intended to support situational awareness for humanitarian and disaster-response practitioners.

HASTE is applied research. Microsoft does not offer HASTE as a commercial product or service, and the workflow has not been designed, tested, evaluated, or validated for use in production deployments or for use of autonomous decision-making. HASTE outputs are not authoritative damage assessments. Outputs from HASTE are preliminary, exploratory signals that require human validation and expert interpretation, especially before any operational use.

## Research Background

Microsoft AI for Good Lab developed HASTE as a research project to determine whether gaps in rapid post-disaster building-damage assessment could be improved. Some existing assessment pipelines (e.g., emergency management service products, manual aircraft / helicopter surveys) often have meaningful latency, geographic coverage gaps, and limited ability to absorb a user's specific situational context within the first 72 hours of an event — which is precisely the window in which humanitarian responders need to triage where to send people, supplies, and attention.

HASTE was designed around two ideas that emerged from earlier in-browser damage-assessment research by Microsoft AI for Good Lab researchers:

- **Train per event, not for the world.** Instead of a single global damage model attempting to generalize across regions and disaster types, HASTE trains a small computer-vision model on a specific event from a small set of human-provided labels. The trade-off is intentional: rapid, event-specific performance over broad generalizability.
- **Keep humans firmly in the loop.** A human operator selects the imagery, labels the samples, reviews the model's outputs, and decides whether and how to share them. The architecture of the workflow assumes — and depends on — informed human oversight at every step.

## Intended Use

The HASTE research is intended for:

- **Contributing information to rapid preliminary damage assessment** in the first hours and days after a disaster, to support situational awareness and inform — but not replace — expert humanitarian assessment.
- **Supplementing informational signals** for downstream humanitarian decision-makers (NGOs, UN agencies, government users) about where damage may be concentrated within affected areas.
- **Exploratory geospatial analysis** by trained humanitarian / disaster-response practitioners working with post-event imagery.
- **Methodology research** on rapid event-specific damage modeling, including evaluation of imagery sources, label workflows, and aggregation approaches.

HASTE's outputs may help highlight **potential building-level damage patterns** when analyzing post-disaster imagery against an external building-footprint dataset.

## Out-of-Scope/ Unintended Uses

**Users should not rely solely on HASTE outputs as the basis for decisions that could impact safety, property, or human life.**

HASTE and its outputs are **NOT** intended, designed, evaluated, or tested to be used:

- As **authoritative damage assessments** or **ground truth** for or in any operational, governmental, insurance, or public-reporting context or purpose;
- As the **sole or primary basis** for high-stakes decisions, including but not limited to, emergency response prioritization, resource allocation, search-and-rescue tasking, or public reporting of damage extent;
- For **autonomous operational decision-making** or an alerting system of any kind.
- As a **replacement** for established assessment tools, in-field surveys, sensor data, ground-truth reports, or expert judgment; or
- For **decision-making without human review and corroboration** by a qualified humanitarian or geospatial expert and additional data.

Users should be aware of and adhere to applicable laws or regulations that are relevant to their use.

## How HASTE Works

At a high level, the HASTE workflow proceeds through six steps, each of which depends on a human operator's input or judgment:

1.  **Imagery selection.** A trained operator selects post-disaster satellite or aerial imagery covering the affected area. HASTE supports a bring-your-own-imagery posture and has been used with Planet, Airbus Foundation, Vantor, Sentinel-1/2, Copernicus, and NOAA imagery, among others. Imagery quality, spatial resolution, off-nadir angle, cloud cover, haze, and time-of-day all materially affect the model's behavior.
2.  **Manual sample labeling.** The operator manually labels a small set of imagery samples (typically into categories such as `damaged`, `non-damaged`, and `background`). The number and quality of these labels — not a pre-trained global model — are what teach HASTE what damage looks like for a particular event in a particular place.
3.  **Local, event-specific model training.** HASTE trains a computer-vision model locally against the human-labeled samples for that specific event. The model is **intentionally optimized for rapid event-specific performance, not generalizable accuracy**: it is fit to one disaster, in one region, with one operator's labels, and is not expected to perform outside those conditions.
4.  **Per-pixel damage prediction.** The locally trained model is run against the broader imagery footprint to produce per-pixel predictions of likely damage indicators.
5.  **Aggregation with external building footprints.** Per-pixel predictions are intersected with an external building-footprint dataset — typically OpenStreetMap, Microsoft Building Footprints, or user-provided footprints — to produce **building-level damage estimates**.
6.  **Human review and distribution.** The operator reviews the building-level outputs, validates against any other available signals, and decides whether and how to package and share them (commonly as a GeoPackage). When outputs are distributed via external channels (e.g., the Humanitarian Data Exchange, ArcGIS feature services, other GIS systems), they carry usage notices reinforcing that they are research outputs requiring further validation.

Outputs from HASTE are highly dependent on:

- **The quality and representativeness of the operator's labels.**
- **The characteristics of the input imagery** (resolution, cloud cover, haze, off-nadir angle, time of day, spatial alignment with the building-footprint dataset).
- **The disaster context** (event type, building stock, terrain, the speed at which post-event imagery becomes available).

HASTE does **not** independently confirm damage and does **not** incorporate contextual data such as ground reports, sensor networks, weather data, or expert validation. Outputs must be interpreted by qualified people using additional independent information sources before any operational action is taken.

## Data Sources and Data Handling

**Imagery sources.** HASTE operates on bring-your-own imagery. In Microsoft AI for Good Lab activations, imagery has typically been sourced from:

- **Planet**
- **Airbus Foundation**
- **Vantor**
- **Sentinel-1 and Sentinel-2** (open ESA Copernicus data);
- **Copernicus Emergency Management Service** products (open EU data);
- **NOAA** (open US-government imagery);
- **User-provided imagery**

**Building-footprint sources.** HASTE aggregates per-pixel predictions against externally maintained building-footprint datasets, most commonly:

- **OpenStreetMap** (via Overture and direct OSM extracts);
- **Microsoft Building Footprints** (open dataset);
- **User-provided footprints** when available for a given region.

**Labels.** Labels are produced by a trained human operator for each event. Labels are not reused across events and are not accumulated into a global training corpus.

**Personal data and identification.** HASTE is **not designed to identify individuals**. It does not ingest, label, or output personal data. Where input imagery may incidentally contain person-scale features, those features are not the target of the model and are not preserved as identifiable signal in HASTE outputs.

**Custody, governance, and downstream use.**

- For Microsoft AI for Good Lab activations, outputs are typically published as **open data** through the Humanitarian Data Exchange (HDX) and / or via Microsoft AI for Good Lab ArcGIS feature services, alongside accompanying usage notices that reinforce the human-validation requirement.
- For self-deployed instances of HASTE, the **user controls** imagery handling, label storage, output retention, and downstream distribution under that user's own data-handling policies.
- HASTE itself does not transmit operational data back to Microsoft; user-self-deployed instances are operationally independent of Microsoft.

## Limitations and Known Risks

The HASTE workflow has well-understood limitations. These are not edge cases — they are intrinsic to a human-in-the-loop, event-specific, rapid damage-assessment design:

- **Sensitivity to limited training data.** Because each event is trained from a small set of human labels, model behavior is heavily influenced by the choice and quality of those labels. Different operators on the same event can produce materially different outputs.
- **Imagery quality variability.** Cloud cover, haze, low light, off-nadir capture angles, and limited spatial resolution can all degrade model performance — sometimes severely. PlanetScope imagery, for example, sits below the ~30 cm resolution threshold typically preferred by building-detection models; HASTE compensates by leveraging external building footprints, which works in regions with good footprint coverage and works less well in regions where footprint coverage is sparse.
- **Spatial misalignment.** Post-event imagery and the building-footprint dataset may not align perfectly, especially in dense urban areas, in regions with rapid recent development, or where ground deformation has occurred.
- **Rapid labeling / retraining inaccuracies.** The speed at which HASTE retrains for a new event introduces the risk of label noise, ambiguous boundaries between damage classes, and model overfitting to a small label set.
- **Event-specific by design — does not generalize.** A HASTE model trained for Hurricane Melissa in the Caribbean is not expected to produce useful outputs for, say, an earthquake in Türkiye. This is intentional, and it also means HASTE cannot be deployed as a persistent multi-event monitoring model.
- **False positives.** Shadows, infrastructure changes unrelated to the disaster (construction, demolition), cloud and atmospheric artifacts, vegetation changes, and certain lighting conditions can be misclassified as damage indicators.
- **False negatives.** Subtle structural damage (e.g., partial roof loss visible only in oblique imagery), damage obscured by cloud or shadow, and damage at scales below the imagery's effective resolution may be under-detected.
- **Building-footprint dataset gaps.** OpenStreetMap and Microsoft Building Footprints have meaningfully variable coverage globally. Coverage tends to be weakest in the Global South, in informal settlements, in conflict-affected areas, and in areas of rapid recent construction — precisely the populations and regions most relevant to humanitarian response.
- **Geographic and environmental bias.** Performance can degrade outside the conditions represented in the operator's labels for that event — for example, when building stock varies materially across an affected region but labels were drawn from only one neighborhood.
- **Flood depth not estimated.** HASTE intersects flood layers with building footprints but does not estimate water depth at building level.
- **No incorporation of contextual data.** HASTE does not ingest ground-truth reports, weather data, social media signals, or sensor networks. Outputs are imagery-derived only.

**Representative examples of incorrect or ambiguous outputs.**

> During the Hurricane Melissa response in 2025, an initial training set of 153 labels generated incorrect labels for impacted buildings. One set of buildings was identified as “20% Damaged” when in fact they were “100% Damaged.” The labeler identified the issue through visual validation of the labels in the visualizer tool, and to rectify the issue, added an additional 107 labels to the training set and trained the model. Users need to validate the output before fully using the analysis.

As a research artifact, the HASTE workflow has not been tested to meet the reliability, accuracy, or safety thresholds required for operational deployment as an authoritative assessment system.

## Safeguards, Human Oversight, and Mitigation

The HASTE workflow is structured around the principle that a human operator is responsible for every output. To reduce the risk of misuse:

- **Human-in-the-loop is structural, not advisory.** A human operator selects the imagery, labels the samples that train the model, reviews the per-pixel predictions, validates the building-level aggregation, and decides whether and how to distribute the output. There is no autonomous mode.
- **Outputs require human validation and expert interpretation prior to use.** This is the explicit position of the project, the expectation set with every partner, and the language carried on every public distribution channel.
- **Cross-validation with other data sources.** Users are expected to cross-validate and corroborate HASTE outputs, particularly in high-stakes contexts, against ground-truth reports, additional imagery sources, sensor networks, and partner-specific assessment workflows before acting on them.
- **Distribution platforms carry usage notices.** Outputs distributed via the Humanitarian Data Exchange, ArcGIS feature services, and partner GIS systems carry notices reinforcing the exploratory-and-preliminary framing of HASTE and the requirement for human validation.
- HASTE is released under the MIT License and is provided “AS-IS,” without warranties of any kind.
- Users are responsible for operational validation including validating outputs, implementing appropriate safeguards, and applying their own internal review and governance processes to outputs they generate. Users should follow responsible AI best practices, including assessing and mitigating risks associated with their use.

## Incident response and escalation

- **Reporting issues.** Any issues with HASTE outputs, unexpected behavior, suspected misuse, or safety concerns should be reported via:
  - GitHub Issues on the public `microsoft/haste` repository for technical issues, model behavior concerns, and reproducibility questions; and
  - Microsoft AI for Good Lab maintainer contact for operational concerns or sensitive incidents.
- **Suspension of use.** If a widespread inaccuracy, misuse pattern, or harmful downstream outcome is identified, Microsoft’s AI for Good Lab may publish guidance recommending temporary suspension or restricted use of the HASTE workflow until the issues are better understood or resolved. Users should consider and evaluate such guidance in light of their context and risk posture.
- **No use as an alerting / triggering system without independent verification.** HASTE outputs should not be used to trigger public alerts, response actions, resource deployments, or public communications without independent verification using additional data and human oversight.

## Research Outputs

HASTE produces research and decision-support outputs intended to support **situational awareness, rapid preliminary damage assessment, exploratory analysis, and methodology research**. HASTE outputs are not authoritative assessments, are not ground truth, and should not be relied upon for high‑stakes decisions such as emergency response prioritization, resource allocation, or public reporting of damage extent.

HASTE is **not** intended to be used as an operational damage-assessment system of record, an authoritative damage register, or a basis for autonomous response.

When HASTE outputs are distributed publicly — including through the Humanitarian Data Exchange, ArcGIS feature services, partner GIS systems, or any other channel — those outputs carry usage notices that:

- Explicitly **warn against over-reliance** on HASTE outputs;
- **Encourage cross-validation** with other data sources, ground-truth reports, and additional imagery;
- **Reinforce that HASTE is intended for exploratory analysis and preliminary damage assessment** rather than definitive decision-making; and
- **Identify HASTE as the source** of the analytical layer, alongside the imagery provider and the building-footprint dataset used for aggregation, so downstream users can independently assess provenance.

## License

MIT License

Nothing disclosed here, including the Out of Scope Uses section, should be interpreted as or deemed a restriction or modification to the license the code is released under.
