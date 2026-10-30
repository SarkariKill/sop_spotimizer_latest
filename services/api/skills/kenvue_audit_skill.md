# Kenvue Global SOP & WI Audit & Scoring Skill
**Version**: 3.0.0  
**Domain**: Quality Assurance, Regulatory Compliance & Operational Excellence  
**Standard**: Kenvue Master SOP-WI Architecture (SOP-STD-001)  
**Source of Truth**: Master SOP-WI Template_en-EN

---

## 1. Objective & Purpose
This skill defines the authoritative criteria and scoring rubrics used to evaluate Standard Operating Procedures (SOPs) and Work Instructions (WIs) against Kenvue Global Quality Standards. It establishes quantifiable evaluation metrics and produces actionable, user-selectable remediation points to drive document optimization.

---

## 2. Kenvue Standard Section Hierarchy
An approved Kenvue SOP must strictly adhere to the following section structure:

### Mandatory Sections (Must Be Present in Every SOP):
| Section # | Required Section Title | Scope & Quality Criteria |
| :---: | :--- | :--- |
| **1.0** | **Purpose** | Concise statement defining requirements and process steps for [Document Title/Process] for Kenvue. |
| **2.0** | **Scope** | Explicitly defines 2.1 (process covered), 2.2 (applicable regions, locations, or departments), and 2.3 (out of scope processes). |
| **3.0** | **Key Terms** | Critical terms specific to this document listed in alphabetical order. Must cite `FRM-0009808: Glossary of Terms`. Format MUST be a table: `\| Term \| Definition \|`. Acronyms must NOT be in Key Terms; spell them out on first use. |
| **4.0** | **Roles and Responsibilities** | Format MUST be a table: `\| Role \| Responsibilities \|` detailing functional areas and training audiences. Operational roles MUST be capitalized throughout the document. |
| **7.0** | **Procedure** | Step-by-step operating instructions. Formatted as Process Breakdown (7.1 Step Name, 7.1.1 Process) or Table format (`\| Role \| Instruction Steps \|`). Must use active imperative command style with `must` for requirements and explicit numerical tolerances. |

### Required Sections (Indicate "N/A" if Not Applicable):
| Section # | Required Section Title | Scope & Quality Criteria |
| :---: | :--- | :--- |
| **5.0** | **Requirements** | Specific process requirements (5.1). If not applicable, explicitly indicate "N/A". |
| **8.0** | **References** | Conservative list of directly cited documents in hierarchical order. Format MUST be a table: `\| Reference \| Document \|`. Must include 8.1 FRM-0009808. If none, indicate "N/A". |
| **9.0** | **Appendices** | Operational checklists, logsheets, or supplementary materials (Appendix 1: Title). If none, indicate "N/A". |
| **—** | **Document Revision History** | Structured table at the bottom: `\| Version Number \| Section \| Description of Change \| Reason for Change \| Document Owner \|`. Version 1 for new documents. |

### Optional Section:
| Section # | Section Title | Scope & Quality Criteria |
| :---: | :--- | :--- |
| **6.0** | **Process Flow** | Visual flowchart diagram, decision table (`\| Stage / Decision \| Flow relationship / activity \|`), or reference to Appendix when applicable. |

---

## 3. Writing Standards & Lexical Rules

### Rule 1: Imperative Command Style & Modal Vocabulary
* **"Must"**: Use for a mandatory requirement or obligation.
* **"Must not"**: Use for a prohibition.
* **"Can"**: Use for ability or when the task is optional.
* **"May"**: Use for permission or discretionary action.
* **"Might"**: Use when there is a greater likelihood that the action will come to fruition.

### Rule 2: Prohibited Terms (Strict Disqualification)
* **Zero tolerance** for the words: **"should"**, **"shall"**, or **"will"**.
* Every occurrence of "should", "shall", or "will" must be replaced with "must", "can", or "may" according to intent.

### Rule 3: Role Capitalization
* Operational roles must be capitalized throughout the document (e.g., *"Submit the report to the Approver for review and approval"*, *"The Operator must verify drum speed"*).

### Rule 4: Quantified Tolerances & Technical Precision
* All operating parameters must include explicit allowable numerical tolerances (e.g., `12,500 ± 50 RPM`, `4.0 ± 0.5 °C`, `15 ± 2 PSI`, `10 to 15 minutes`).
* Zero tolerance for vague adverbs like *"properly"*, *"approximately"*, *"sufficient amount"*, or *"as needed"*.

---

## 4. Scoring Rubric Specifications

### Metric 1: Template Compliance Score (`template_score`: 0–100)
Evaluates architectural alignment with Kenvue Master SOP sections:
* **90–100**: All mandatory sections (1.0, 2.0, 3.0, 4.0, 7.0), required sections (5.0, 8.0, 9.0), required tables (Key Terms, Roles, Revision History), and FRM-0009808 citation are present and properly formatted.
* **75–89**: Core sections present; minor gaps in dedicated tables or missing N/A declarations in non-applicable sections.
* **60–74**: Basic procedure present but lacks formal roles table, key terms glossary table, or revision history table.
* **< 60**: Unstructured or legacy text lacking standard numbering, missing mandatory sections, or missing formal document headers.

### Metric 2: Readability & Command Voice Score (`readability_score`: 0–100)
Evaluates sentence complexity, clarity, and directive tone:
* **Imperative Command Voice**: Steps must open with strong action verbs (*"Inspect"*, *"Sanitize"*, *"Calibrate"*, *"Verify"*), using "must" for obligations.
* **Prohibited Words Penalty**: Penalize document for every instance of "should", "shall", or "will".
* **Role Capitalization**: Operational roles must be consistently capitalized.
* **Clarity**: Concise sentences (< 25 words/step), eliminating vague modifiers.

### Metric 3: Technical Quality & Tolerance Score (`quality_score`: 0–100)
Evaluates precision, hazard management, and verifiable controls:
* **Quantified Tolerances**: Operating parameters must include explicit allowable tolerances (± limits).
* **Critical Safety Alerts**: High-risk steps must feature prominent Warning / Caution callouts preceding the action.
* **Asset Integration**: High-resolution process flowcharts, equipment staging figures, and parameter tables embedded in respective sections.

### Metric 4: Composite Average Score (`average_score`: 0–100)
$$\text{Average Score} = \text{round}\left(\frac{\text{Template Score} + \text{Readability Score} + \text{Quality Score}}{3}\right)$$

---

## 5. Remediation Suggestion Taxonomy
When auditing an SOP, the auditor must generate 4 to 6 concrete, mutually exclusive improvement points presented as user-selectable checkboxes:
1. `sug_struct`: **Standardize Section Hierarchy to Kenvue Format** — Align headings into standard Kenvue numbering (1.0 Purpose, 2.0 Scope, 3.0 Key Terms, 4.0 Roles, 5.0 Requirements, 7.0 Procedure, 8.0 References, 9.0 Appendices, Revision History).
2. `sug_terms`: **Format Section 3.0 Key Terms as Alphabetical Glossary Table** — Insert standard Term / Definition table and reference FRM-0009808.
3. `sug_roles`: **Add Section 4.0 Roles and Responsibilities Table** — Create formal Role / Responsibilities matrix with capitalized roles.
4. `sug_imperative`: **Convert Procedural Steps to Active Imperative Voice** — Replace prohibited words ('should', 'shall', 'will') with imperative 'must' and active command verbs.
5. `sug_tolerances`: **Incorporate Quantified Numerical Tolerances (±)** — Replace vague estimates with explicit measurable limits (± RPM, ± °C, ± PSI).
6. `sug_revision`: **Add Standardized Document Revision History Table** — Add formal version tracking, change description, reason for change, and Document Owner.
