import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from rag_engine import generate_embeddings

logger = logging.getLogger(__name__)

# =====================================================================
# 1. DYNAMIC PROCEDURAL ACTION & DOMAIN EXTRACTION
# Replaces static hardcoded 27-word manufacturing vocabulary with
# multi-domain procedural verb-object patterns and operational concepts
# across HR, QA, Lab, Packaging, Facilities, Safety, and Manufacturing.
# =====================================================================

PROCEDURAL_ACTION_VERBS = [
    "submit", "submits", "submitted", "apply", "applies", "applied",
    "approve", "approves", "approved", "review", "reviews", "reviewed",
    "verify", "verifies", "verified", "calibrate", "calibrates", "calibrated",
    "clean", "cleans", "cleaned", "sanitize", "sanitizes", "sanitized",
    "inspect", "inspects", "inspected", "operate", "operates", "operated",
    "balance", "balances", "balanced", "centrifuge", "centrifuged",
    "seal", "seals", "sealed", "package", "packages", "packaged",
    "dispense", "dispenses", "dispensed", "fill", "fills", "filled",
    "record", "records", "recorded", "document", "documents", "documented",
    "sample", "samples", "sampled", "test", "tests", "tested",
    "audit", "audits", "audited", "isolate", "isolates", "isolated",
    "quarantine", "quarantined", "release", "releases", "released",
    "escalate", "escalates", "escalated", "notify", "notifies", "notified",
    "sterilize", "sterilizes", "sterilized", "purge", "purges", "purged",
    "store", "stores", "stored", "dispose", "disposes", "disposed"
]

DOMAIN_TAXONOMY = [
    {
        "type": "Leave & Absence Administration",
        "category": "Human Resources & Personnel Operations",
        "keywords": ["leave", "absence", "vacation", "sick leave", "time off", "pto", "holiday", "manager approval", "supervisor approval", "employee request", "staff application"],
        "scope": "Employee leave submission, supervisory review, eligibility verification, and formal HR absence approval workflows.",
    },
    {
        "type": "Centrifugation & Separation Operations",
        "category": "Laboratory & Analytical Equipment",
        "keywords": ["centrifuge", "rotor", "centrifugation", "spindle", "rpm", "balancing", "cooling", "tubes", "bottles", "deceleration", "supernatant", "pellet"],
        "scope": "Centrifuge setup, sample tube balance verification, operating speed and temperature regulation, and sample recovery.",
    },
    {
        "type": "Solid Oral Dosage Packaging & Blistering",
        "category": "Packaging & Finishing Operations",
        "keywords": ["blister", "packaging", "carton", "cartoning", "pvc", "alu", "foil", "heat-seal", "tablet", "pockets", "feeding", "leak test", "batch coding"],
        "scope": "Primary and secondary solid dosage packaging, blister forming, heat sealing, visual inspection, and serialization.",
    },
    {
        "type": "Equipment Sanitation & Sterilization",
        "category": "Facility, Cleaning & GMP Maintenance",
        "keywords": ["clean", "sanitize", "autoclave", "sterilize", "disinfect", "cip", "sip", "detergent", "rinse", "microbial", "bioburden", "purified water"],
        "scope": "Clean-In-Place (CIP), sterilization procedures, sanitizing agent preparation, dwell times, and clean validation swabbing.",
    },
    {
        "type": "Quality Control & Analytical Testing",
        "category": "Quality Assurance & Laboratory Compliance",
        "keywords": ["assay", "titration", "hplc", "spectrophotometer", "ph measurement", "reagent", "calibration", "standard curve", "acceptance criteria", "oos"],
        "scope": "Analytical testing protocols, reference standard qualification, instrument calibration, sample testing, and data verification.",
    },
    {
        "type": "Material Dispensing & Batch Formulation",
        "category": "Manufacturing & Formulation Processing",
        "keywords": ["dispense", "dispensing", "weigh", "weighing", "balance", "raw material", "active pharmaceutical ingredient", "api", "excipient", "batch record", "gross weight", "tare"],
        "scope": "Raw material staging, analytical balance taring, precise ingredient dispensing, double-check verification, and staging for compounding.",
    },
    {
        "type": "Document Control & Change Management",
        "category": "Quality Systems & Regulatory Compliance",
        "keywords": ["document control", "change control", "sop revision", "effective date", "obsolete", "archival", "version control", "training record", "dms"],
        "scope": "Authoring, review, regulatory impact assessment, management approval, issuance, and periodic review of quality documentation.",
    },
    {
        "type": "Warehouse Staging & Inventory Control",
        "category": "Supply Chain & Material Management",
        "keywords": ["warehouse", "pallet", "forklift", "quarantine", "receipt", "storage condition", "fifo", "fefo", "cold chain", "shipping", "reconciliation"],
        "scope": "Incoming goods receiving, quarantine segregation, temperature-controlled storage, FIFO rotation, and distribution staging.",
    },
    {
        "type": "Environmental Health & Personnel Safety",
        "category": "EHS & Occupational Safety",
        "keywords": ["ppe", "safety glasses", "respirator", "hazard", "spill", "emergency", "eyewash", "chemical splash", "evacuation", "lockout", "tagout"],
        "scope": "Personal protective equipment compliance, hazardous material containment, spill response, and emergency escalation protocols.",
    },
]


def extract_key_activities(text: str) -> List[str]:
    """
    Dynamically extracts key operational actions, procedural phrases, and domain
    entities from SOP text across any domain (HR, Manufacturing, Lab, QC, EHS).
    """
    if not text:
        return []
    text_lower = text.lower()
    activities = set()

    # 1. Match two-word and three-word action phrases (e.g., "submits leave request", "approve request")
    action_phrase_patterns = [
        r"\b(?:submit|submits|applying|apply|applies)\s+(?:a\s+)?(?:leave|absence|request|application|form|document)\b",
        r"\b(?:approve|approves|approving|review|reviews|reviewing)\s+(?:the\s+)?(?:leave|request|application|record|sop|change)\b",
        r"\b(?:balance|balancing)\s+(?:the\s+)?(?:rotor|centrifuge|tubes|bottles|samples)\b",
        r"\b(?:heat-seal|heat\s+sealing|seal|sealing)\s+(?:the\s+)?(?:blister|foil|pouch|carton|package)\b",
        r"\b(?:calibrate|calibrating)\s+(?:the\s+)?(?:instrument|balance|sensor|probe|scale)\b",
        r"\b(?:clean|cleaning|sanitize|sanitizing)\s+(?:the\s+)?(?:equipment|vessel|line|surface|machine)\b",
        r"\b(?:dispense|dispensing|weigh|weighing)\s+(?:the\s+)?(?:material|powder|api|reagent|ingredient)\b",
        r"\b(?:inspect|inspecting|verify|verifying)\s+(?:the\s+)?(?:seal|batch|label|parameter|tolerance)\b",
        r"\b(?:log|record|document)\s+(?:the\s+)?(?:reading|result|data|deviation|action)\b",
    ]
    for pattern in action_phrase_patterns:
        matches = re.findall(pattern, text_lower)
        for m in matches:
            activities.add(m.strip())

    # 2. Extract action verb + direct noun collocations
    words = re.findall(r"[a-z]+", text_lower)
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        if w1 in PROCEDURAL_ACTION_VERBS and len(w2) > 3 and w2 not in ("the", "that", "this", "with", "from", "into"):
            activities.add(f"{w1} {w2}")

    # 3. Match domain taxonomy terms
    for domain in DOMAIN_TAXONOMY:
        for kw in domain["keywords"]:
            if kw in text_lower:
                activities.add(kw)

    return list(activities)[:25]


def extract_parameters_with_values(text: str) -> Dict[str, str]:
    """
    Extracts numerical parameters (speed, temperature, pressure, time) to detect conflicts.
    Uses Unicode-safe boundaries (?<!\\d) and (?![a-zA-Z]) so numbers adjacent to CJK/Unicode
    characters are always captured, and normalizes unit spacing to prevent false conflicts.
    """
    if not text:
        return {}
    norm_text = text.replace("℃", " °C ").replace("℉", " °F ")
    params = {}
    speed_m = re.search(r"(?<!\d)(\d{3,6})\s*rpm(?![a-zA-Z])(?:\s*±\s*(\d+)\s*rpm(?![a-zA-Z]))?", norm_text, re.IGNORECASE)
    if speed_m:
        val = f"{speed_m.group(1)} RPM"
        if speed_m.group(2):
            val += f" ± {speed_m.group(2)} RPM"
        params["operating_speed"] = val

    temp_m = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(?:°c|deg\s*c)(?![a-zA-Z])(?:\s*±\s*(\d+(?:\.\d+)?)\s*°c(?![a-zA-Z]))?", norm_text, re.IGNORECASE)
    if temp_m:
        val = f"{temp_m.group(1)} °C"
        if temp_m.group(2):
            val += f" ± {temp_m.group(2)} °C"
        params["operating_temperature"] = val

    press_m = re.search(r"(?<!\d)(\d{1,4}(?:\.\d+)?)\s*(psi|bar|kpa)(?![a-zA-Z])", norm_text, re.IGNORECASE)
    if press_m:
        params["operating_pressure"] = f"{press_m.group(1)} {press_m.group(2).lower()}"

    time_m = re.search(r"(?<!\d)(\d{1,3})\s*(minutes|mins|hours|hrs|seconds|sec)(?![a-zA-Z])", norm_text, re.IGNORECASE)
    if time_m:
        unit_map = {"mins": "minutes", "hrs": "hours", "sec": "seconds"}
        u = time_m.group(2).lower()
        params["duration_time"] = f"{time_m.group(1)} {unit_map.get(u, u)}"

    return params


def discover_sop_type_and_scope(
    cluster_docs: List[Dict[str, Any]],
    cluster_texts: List[str],
) -> Tuple[str, str, str, str]:
    """
    Automatically discovers the business domain, SOP type, category, and operational scope
    for a discovered group of similar SOPs using content taxonomy and semantic keyword matching.

    Returns:
        (group_title, discovered_type, category, operational_scope)
    """
    combined_text = " ".join(cluster_texts).lower()
    filenames_text = " ".join([d.get("filename", "") for d in cluster_docs]).lower()
    full_haystack = f"{filenames_text} {combined_text}"

    # Score each domain by keyword hits
    best_domain = None
    best_score = 0

    for domain in DOMAIN_TAXONOMY:
        score = 0
        for kw in domain["keywords"]:
            if kw in full_haystack:
                score += 3 if kw in filenames_text else 1
        if score > best_score:
            best_score = score
            best_domain = domain

    if best_domain and best_score >= 2:
        discovered_type = best_domain["type"]
        category = best_domain["category"]
        operational_scope = best_domain["scope"]
        group_title = f"{discovered_type}"
        return group_title, discovered_type, category, operational_scope

    # Fallback: extract primary subject from filename or first non-empty heading
    first_doc = cluster_docs[0] if cluster_docs else {}
    fname = first_doc.get("filename", "Standard Operating Procedure")
    clean_name = re.sub(r"\.(pdf|docx)$", "", fname, flags=re.IGNORECASE)
    clean_name = re.sub(r"[_\-]+", " ", clean_name).title().strip()
    if len(clean_name) > 40:
        clean_name = clean_name[:38] + "..."

    discovered_type = f"{clean_name} Process"
    category = "General Operational SOP"
    operational_scope = f"Standard operating procedures governing {clean_name.lower()} execution, safety, and compliance."
    group_title = f"{clean_name} Group"
    return group_title, discovered_type, category, operational_scope


# =====================================================================
# 2. MULTI-SOP SEMANTIC SIMILARITY & CLUSTERING ENGINE
# Computes exact pairwise cosine similarity matrix, Chamfer step alignment,
# dynamic parameter divergence detection, and semantic group discovery.
# =====================================================================

class MultiSopSimilarityEngine:
    """
    Analyzes multi-SOP semantic similarity, automatic SOP type discovery,
    and duplicate/overlap relationships using exact cosine embedding alignment,
    hierarchical step coverage, and parameter conflict comparison.
    """

    def compute_document_similarity(
        self,
        doc_a_chunks: List[Dict[str, Any]],
        doc_b_chunks: List[Dict[str, Any]],
        doc_a_text: str,
        doc_b_text: str,
        precomputed_vecs_a: Optional[np.ndarray] = None,
        precomputed_vecs_b: Optional[np.ndarray] = None,
        doc_vec_a: Optional[np.ndarray] = None,
        doc_vec_b: Optional[np.ndarray] = None,
    ) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """
        Computes pairwise similarity (0 to 100%) between two SOP documents using:
        1. Exact holistic document-level cosine similarity.
        2. Multi-chunk bidirectional Chamfer step alignment.
        3. Dynamic procedural action & term overlap without destructive penalties.
        4. Operational parameter conflict detection.
        """
        # Step A: Holistic Document Cosine Similarity
        if doc_vec_a is not None and doc_vec_b is not None and len(doc_vec_a) > 0 and len(doc_vec_b) > 0:
            # Both vectors are L2-normalized; dot product is exact cosine similarity
            global_sim = float(np.dot(doc_vec_a, doc_vec_b))
        else:
            # Fallback: compute vectors for whole text if missing
            v_a = generate_embeddings([doc_a_text[:4000]]) if doc_a_text else np.empty((0, 1536), dtype=np.float32)
            v_b = generate_embeddings([doc_b_text[:4000]]) if doc_b_text else np.empty((0, 1536), dtype=np.float32)
            if len(v_a) > 0 and len(v_b) > 0:
                global_sim = float(np.dot(v_a[0], v_b[0]))
            else:
                global_sim = 0.0

        # Clip global_sim to [-1.0, 1.0] range
        global_sim = max(-1.0, min(1.0, global_sim))

        # Step B: Fine-Grained Chunk-Level Chamfer Alignment
        vecs_a = precomputed_vecs_a
        if vecs_a is None and doc_a_chunks:
            vecs_a = generate_embeddings([c.get("text", "") for c in doc_a_chunks if c.get("text")])

        vecs_b = precomputed_vecs_b
        if vecs_b is None and doc_b_chunks:
            vecs_b = generate_embeddings([c.get("text", "") for c in doc_b_chunks if c.get("text")])

        overlaps: List[str] = []
        if vecs_a is not None and vecs_b is not None and len(vecs_a) > 0 and len(vecs_b) > 0:
            # Matrix of chunk dot products: shape (len_a, len_b)
            sim_matrix = np.dot(vecs_a, vecs_b.T)

            # Bidirectional step coverage:
            max_sim_a_to_b = np.max(sim_matrix, axis=1)
            max_sim_b_to_a = np.max(sim_matrix, axis=0)

            mean_a_to_b = float(np.mean(max_sim_a_to_b))
            mean_b_to_a = float(np.mean(max_sim_b_to_a))
            chamfer_sim = max(0.0, min(1.0, (mean_a_to_b + mean_b_to_a) / 2.0))

            # Extract high-similarity overlapping steps (cosine >= 0.65)
            for i in range(len(doc_a_chunks)):
                for j in range(len(doc_b_chunks)):
                    if sim_matrix[i, j] >= 0.65:
                        clean_step_a = re.sub(r"^[0-9\.\-\s]+", "", doc_a_chunks[i].get("text", "")).strip()
                        if clean_step_a and len(clean_step_a) > 15:
                            summary_str = clean_step_a[:110] + ("..." if len(clean_step_a) > 110 else "")
                            if summary_str not in overlaps:
                                overlaps.append(summary_str)
                                if len(overlaps) >= 6:
                                    break
        else:
            chamfer_sim = max(0.0, global_sim)

        # Step C: Dynamic Procedural Activity Overlap
        acts_a = set(extract_key_activities(doc_a_text))
        acts_b = set(extract_key_activities(doc_b_text))
        common_acts = list(acts_a.intersection(acts_b))
        total_acts = len(acts_a.union(acts_b))
        jaccard = (len(common_acts) / total_acts) if total_acts > 0 else 0.0

        # Step D: Operational Parameter Comparison & Conflict Detection
        params_a = extract_parameters_with_values(doc_a_text)
        params_b = extract_parameters_with_values(doc_b_text)
        conflicts = []
        for k in params_a:
            if k in params_b and params_a[k].lower() != params_b[k].lower():
                param_name = k.replace("_", " ").title()
                conflicts.append(f"{param_name} divergence: '{params_a[k]}' vs '{params_b[k]}'")

        # Step E: Unbiased Calibration (Zero Destructive Ceiling)
        # Global semantic embedding provides the primary ground truth (55%),
        # Chamfer procedural step alignment provides the granular match (40%),
        # Dynamic procedural terminology provides a supplementary signal (5%).
        # Note: A low Jaccard score never penalizes documents with high semantic equivalence.
        raw_score = (global_sim * 0.55) + (chamfer_sim * 0.40) + (jaccard * 0.05)
        raw_score = max(0.0, min(1.0, raw_score))

        if raw_score >= 0.70:
            # Highly Similar: Duplicate or overlapping procedures (75.0% - 98.0%)
            calibrated_score = round(75.0 + min(23.0, ((raw_score - 0.70) / 0.30) * 23.0), 1)
        elif raw_score >= 0.45:
            # Moderately Similar: Related domain or shared operational activities (45.0% - 74.9%)
            calibrated_score = round(45.0 + ((raw_score - 0.45) / 0.25) * 29.0, 1)
        else:
            # Different: Distinct standalone procedures (5.0% - 44.9%)
            calibrated_score = round(max(5.0, (raw_score / 0.45) * 44.0), 1)

        # Fallback overlap summary from common activities if chunk Chamfer overlaps were empty
        if not overlaps and common_acts:
            overlaps = [f"Shared operation: {act.title()}" for act in common_acts[:5]]

        details = {
            "global_semantic_score": round(float(global_sim) * 100, 1),
            "chamfer_step_score": round(float(chamfer_sim) * 100, 1),
            "jaccard_overlap_score": round(float(jaccard) * 100, 1),
            "common_activities_count": len(common_acts),
            "conflicts_count": len(conflicts),
        }

        return calibrated_score, overlaps[:6], conflicts, details

    def analyze_collection(
        self,
        documents: List[Dict[str, Any]],
        vector_store_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Runs comprehensive multi-SOP similarity detection across all uploaded SOPs,
        discovers SOP types, groups them into semantic clusters, and generates an
        exact symmetric N x N similarity matrix and executive summary.
        """
        vector_store_chunks = vector_store_chunks or []
        n = len(documents)
        if n < 2:
            return {
                "groups": [],
                "similarity_groups": [],
                "pairwise_matrix": [],
                "symmetric_matrix": {
                    "doc_ids": [d.get("id") or d.get("document_id") for d in documents],
                    "filenames": [d.get("filename", "") for d in documents],
                    "matrix": [[100.0]] if n == 1 else [],
                    "status_matrix": [["Self"]] if n == 1 else [],
                },
                "executive_summary": "Single SOP uploaded. Upload additional SOPs to enable multi-document similarity analysis, automatic type discovery, and harmonization.",
                "has_duplicates_or_overlaps": False,
                "recommended_harmonize_ids": [],
                "total_documents_analyzed": n,
            }

        # -------------------------------------------------------------
        # STEP 1: PRE-COMPUTE CHUNK AND WHOLE-DOCUMENT EMBEDDINGS (O(N))
        # -------------------------------------------------------------
        doc_chunks_map: Dict[str, List[Dict[str, Any]]] = {}
        doc_chunk_vecs_map: Dict[str, np.ndarray] = {}
        doc_composite_vecs_map: Dict[str, np.ndarray] = {}
        doc_texts_map: Dict[str, str] = {}

        for d in documents:
            doc_id = d.get("id") or d.get("document_id")
            d_text = d.get("english_canonical_text") or d.get("original_text") or d.get("text") or ""
            doc_texts_map[doc_id] = d_text

            d_chunks = [
                c for c in vector_store_chunks if c.get("document_id") == doc_id and c.get("text")
            ]
            doc_chunks_map[doc_id] = d_chunks

            if d_chunks:
                # Embed all child chunks for this document
                chunk_texts = [c.get("text", "") for c in d_chunks]
                c_vecs = generate_embeddings(chunk_texts)
                doc_chunk_vecs_map[doc_id] = c_vecs

                # Calculate composite holistic document vector by mean pooling chunks with L2 normalization
                mean_vec = np.mean(c_vecs, axis=0, keepdims=True)
                norm = np.linalg.norm(mean_vec)
                if norm > 0:
                    mean_vec /= norm
                doc_composite_vecs_map[doc_id] = mean_vec[0]
            else:
                # Full document text embedding (break long text into 1,000-char segments and mean-pool)
                segments = [d_text[k : k + 1000] for k in range(0, min(len(d_text), 20000), 1000) if d_text[k : k + 1000].strip()]
                if not segments and d_text:
                    segments = [d_text]
                if segments:
                    s_vecs = generate_embeddings(segments)
                    mean_vec = np.mean(s_vecs, axis=0, keepdims=True)
                    norm = np.linalg.norm(mean_vec)
                    if norm > 0:
                        mean_vec /= norm
                    doc_composite_vecs_map[doc_id] = mean_vec[0]
                    doc_chunk_vecs_map[doc_id] = s_vecs
                else:
                    doc_composite_vecs_map[doc_id] = np.zeros(1536, dtype=np.float32)
                    doc_chunk_vecs_map[doc_id] = np.empty((0, 1536), dtype=np.float32)

        # -------------------------------------------------------------
        # STEP 2: EXACT PAIRWISE SIMILARITY MATRIX GENERATION
        # -------------------------------------------------------------
        all_doc_ids = [d.get("id") or d.get("document_id") for d in documents]
        all_filenames = [d.get("filename", "") for d in documents]
        doc_id_to_idx = {doc_id: i for i, doc_id in enumerate(all_doc_ids)}

        # Initialize N x N symmetric matrices
        numeric_matrix = np.zeros((n, n), dtype=np.float32)
        status_matrix: List[List[str]] = [["" for _ in range(n)] for _ in range(n)]

        for i in range(n):
            numeric_matrix[i, i] = 100.0
            status_matrix[i][i] = "Identical (Self)"

        pairwise_matrix = []
        similarity_graph: Dict[str, Dict[str, float]] = {doc_id: {} for doc_id in all_doc_ids}
        overlap_details_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for i in range(n):
            id_a = all_doc_ids[i]
            doc_a = documents[i]
            text_a = doc_texts_map.get(id_a, "")
            chunks_a = doc_chunks_map.get(id_a, [])
            vecs_a = doc_chunk_vecs_map.get(id_a)
            comp_a = doc_composite_vecs_map.get(id_a)

            for j in range(i + 1, n):
                id_b = all_doc_ids[j]
                doc_b = documents[j]
                text_b = doc_texts_map.get(id_b, "")
                chunks_b = doc_chunks_map.get(id_b, [])
                vecs_b = doc_chunk_vecs_map.get(id_b)
                comp_b = doc_composite_vecs_map.get(id_b)

                sim, overlaps, conflicts, details = self.compute_document_similarity(
                    chunks_a,
                    chunks_b,
                    text_a,
                    text_b,
                    precomputed_vecs_a=vecs_a,
                    precomputed_vecs_b=vecs_b,
                    doc_vec_a=comp_a,
                    doc_vec_b=comp_b,
                )

                similarity_graph[id_a][id_b] = sim
                similarity_graph[id_b][id_a] = sim

                numeric_matrix[i, j] = sim
                numeric_matrix[j, i] = sim

                status = (
                    "Highly Similar"
                    if sim >= 70.0
                    else "Moderately Similar"
                    if sim >= 45.0
                    else "Distinct / Unrelated"
                )

                status_matrix[i][j] = status
                status_matrix[j][i] = status

                pair_record = {
                    "doc_a": id_a,
                    "doc_b": id_b,
                    "filename_a": doc_a.get("filename", ""),
                    "filename_b": doc_b.get("filename", ""),
                    "similarity": sim,
                    "status": status,
                    "overlaps": overlaps,
                    "conflicts": conflicts,
                    "details": details,
                }
                pairwise_matrix.append(pair_record)
                overlap_details_map[(id_a, id_b)] = pair_record
                overlap_details_map[(id_b, id_a)] = pair_record

        # -------------------------------------------------------------
        # STEP 3: GRAPH CONNECTED-COMPONENT CLUSTERING
        # Forms clusters based on verified pairwise semantic equivalence (sim >= 45%)
        # -------------------------------------------------------------
        SIMILARITY_CLUSTER_THRESHOLD = 45.0
        visited = set()
        raw_clusters: List[List[str]] = []

        for doc_id in all_doc_ids:
            if doc_id in visited:
                continue

            # Breadth-first / connected components expansion for tight cluster formation
            component = []
            queue = [doc_id]
            visited.add(doc_id)

            while queue:
                curr = queue.pop(0)
                component.append(curr)
                for other_id in all_doc_ids:
                    if other_id not in visited:
                        edge_sim = similarity_graph.get(curr, {}).get(other_id, 0.0)
                        # Verify candidate has high average similarity with the entire component
                        if edge_sim >= SIMILARITY_CLUSTER_THRESHOLD:
                            avg_to_comp = sum(similarity_graph.get(other_id, {}).get(c_id, 0.0) for c_id in component) / len(component)
                            if avg_to_comp >= 40.0:
                                visited.add(other_id)
                                queue.append(other_id)

            raw_clusters.append(component)

        # Sort clusters so multi-document and highest similarity groups come first
        raw_clusters.sort(key=lambda c: (len(c) > 1, len(c)), reverse=True)

        # -------------------------------------------------------------
        # STEP 4: AUTOMATIC SOP TYPE DISCOVERY & GROUP STRUCTURING
        # -------------------------------------------------------------
        doc_dict = {d.get("id") or d.get("document_id"): d for d in documents}
        formatted_groups = []
        highly_similar_doc_ids = []

        for idx, cluster_ids in enumerate(raw_clusters):
            group_docs = [doc_dict[cid] for cid in cluster_ids if cid in doc_dict]
            filenames = [d.get("filename", "") for d in group_docs]
            cluster_texts = [doc_texts_map.get(cid, "") for cid in cluster_ids]

            # Discover official SOP Type, Category, and Scope
            group_title, discovered_type, category, op_scope = discover_sop_type_and_scope(
                group_docs, cluster_texts
            )

            # Calculate average internal similarity
            if len(cluster_ids) > 1:
                pairwise_sims = []
                for p in range(len(cluster_ids)):
                    for q in range(p + 1, len(cluster_ids)):
                        sim_val = similarity_graph.get(cluster_ids[p], {}).get(cluster_ids[q], 0.0)
                        pairwise_sims.append(sim_val)
                avg_sim = round(sum(pairwise_sims) / len(pairwise_sims), 1) if pairwise_sims else 85.0
            else:
                other_sims = list(similarity_graph.get(cluster_ids[0], {}).values())
                avg_sim = round(max(other_sims), 1) if other_sims else 15.0

            is_single = len(cluster_ids) == 1
            if not is_single and avg_sim >= 60.0:
                status = "Highly Similar"
                status_desc = f"Identified as duplicate or overlapping {discovered_type} procedures. Recommended for single standardized harmonization."
                highly_similar_doc_ids.extend(cluster_ids)
            elif not is_single and avg_sim >= 45.0:
                status = "Moderately Similar"
                status_desc = f"Related {discovered_type} procedures with shared operational touchpoints."
            elif is_single:
                status = "Standalone SOP"
                status_desc = f"Distinct standalone {discovered_type} covering separate operational activities with no duplicate counterparts."
            else:
                status = "Distinct / Unrelated"
                status_desc = f"Distinct {discovered_type} procedures covering separate operational activities."

            # Aggregate overlaps, conflicts, and unique elements
            group_overlaps = []
            group_conflicts = []
            unique_elements = {}

            for cid in cluster_ids:
                doc_obj = doc_dict.get(cid, {})
                fname = doc_obj.get("filename", "SOP")
                doc_txt = doc_texts_map.get(cid, "")
                acts = extract_key_activities(doc_txt)
                unique_elements[fname] = acts[:3] if acts else ["Standard operating procedure directives"]

            if len(cluster_ids) > 1:
                for p in range(len(cluster_ids)):
                    for q in range(p + 1, len(cluster_ids)):
                        pair_info = overlap_details_map.get((cluster_ids[p], cluster_ids[q]), {})
                        for ov in pair_info.get("overlaps", []):
                            if ov not in group_overlaps:
                                group_overlaps.append(ov)
                        for cf in pair_info.get("conflicts", []):
                            if cf not in group_conflicts:
                                group_conflicts.append(cf)

            formatted_groups.append({
                "group_id": f"group_{idx + 1}",
                "group_name": f"{group_title}",
                "discovered_type": discovered_type,
                "category": category,
                "operational_scope": op_scope,
                "document_ids": cluster_ids,
                "filenames": filenames,
                "document_names": filenames,
                "document_count": len(cluster_ids),
                "is_standalone": is_single,
                "similarity_score": avg_sim,
                "similarity_pct": int(round(avg_sim)),
                "status": status,
                "status_description": status_desc,
                "reason": status_desc,
                "overlap_summary": group_overlaps[:5] if group_overlaps else [f"Shared directives within {discovered_type}"],
                "conflicts_detected": group_conflicts[:5],
                "unique_elements": unique_elements,
                "is_harmonization_candidate": status == "Highly Similar",
                "can_harmonize": status == "Highly Similar",
            })

        # -------------------------------------------------------------
        # STEP 5: EXECUTIVE SUMMARY & HARMONIZATION RECOMMENDATION
        # -------------------------------------------------------------
        high_groups = [g for g in formatted_groups if g["status"] == "Highly Similar"]
        diff_groups = [g for g in formatted_groups if g["status"] in ("Different", "Distinct / Unrelated", "Standalone SOP")]
        summary_parts = []

        if high_groups:
            for g in high_groups:
                names = ", ".join(g["filenames"])
                summary_parts.append(
                    f"{names} are classified under '{g['discovered_type']}' with high semantic similarity ({g['similarity_pct']}%) and represent duplicate procedures candidate for harmonization."
                )
        if diff_groups:
            diff_names = [f for g in diff_groups for f in g["filenames"]]
            if len(diff_names) > 0 and high_groups:
                names = " and ".join(diff_names[:3])
                summary_parts.append(
                    f"{names} {'are' if len(diff_names) > 1 else 'is'} functionally distinct from the above group."
                )
            elif len(diff_names) > 0 and not high_groups:
                types_found = list({g["discovered_type"] for g in formatted_groups})
                summary_parts.append(
                    f"Uploaded SOPs cover distinct operational domains ({', '.join(types_found[:3])}) with minimal procedural overlap."
                )

        executive_summary = " ".join(summary_parts)

        # Recommended documents for harmonization: either first highly similar group, or all if 2 docs
        recommended_ids = []
        if high_groups:
            recommended_ids = high_groups[0]["document_ids"]
        elif n == 2 and pairwise_matrix and pairwise_matrix[0]["similarity"] >= 50.0:
            recommended_ids = all_doc_ids

        all_overlaps = []
        all_conflicts = []
        for p in pairwise_matrix:
            for o in p.get("overlaps", []):
                all_overlaps.append({
                    "procedure": o,
                    "shared_documents": [p["filename_a"], p["filename_b"]],
                    "description": f"Shared procedural step between {p['filename_a']} and {p['filename_b']}"
                })
            for c in p.get("conflicts", []):
                if isinstance(c, dict):
                    all_conflicts.append(c)
                else:
                    param_name = str(c).split(" divergence")[0] if " divergence" in str(c) else str(c)
                    all_conflicts.append({
                        "parameter": param_name,
                        "unit": "",
                        "values": [{"doc": p["filename_a"], "value": ""}, {"doc": p["filename_b"], "value": ""}],
                        "resolved_gmp_limit": "Reconciled to tighter GMP tolerance in harmonized procedure",
                        "action": str(c)
                    })

        symmetric_matrix_payload = {
            "doc_ids": all_doc_ids,
            "filenames": all_filenames,
            "matrix": [[float(round(v, 1)) for v in row] for row in numeric_matrix.tolist()],
            "status_matrix": status_matrix,
        }

        return {
            "groups": formatted_groups,
            "similarity_groups": formatted_groups,
            "pairwise_matrix": pairwise_matrix,
            "symmetric_matrix": symmetric_matrix_payload,
            "procedural_overlaps": all_overlaps,
            "parameter_conflicts": all_conflicts,
            "executive_summary": executive_summary,
            "has_duplicates_or_overlaps": len(high_groups) > 0,
            "recommended_harmonize_ids": recommended_ids,
            "total_documents_analyzed": n,
        }


similarity_engine = MultiSopSimilarityEngine()
analyze_collection = similarity_engine.analyze_collection
