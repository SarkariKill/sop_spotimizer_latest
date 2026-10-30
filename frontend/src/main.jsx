import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import { marked } from "marked";
import "./styles.css";

marked.setOptions({
  breaks: true,
  gfm: true,
});

function formatMessageContent(content) {
  if (!content) return "";
  // Convert [Document: filename.pdf, Page X] or [Document: filename.pdf | Page X] to stylish multi-doc badge chips
  let processed = content.replace(/(?:【|\[)Document:\s*([^,|\]]+)(?:,\s*Page|\s*\|\s*Page)[\s\u202f]*(\d+)(?:】|\])/gi, (match, doc, p1) => {
    const cleanDoc = doc.trim();
    return `<span class="page-badge" title="Source Document: ${cleanDoc}"><span class="badge-icon">📑</span> ${cleanDoc} · Page ${p1}</span>`;
  });
  // Convert [Page X] or 【Page X】 or (Page X) to stylish badge chips
  processed = processed.replace(/(?:【|\[)Page[\s\u202f]*(\d+)(?:】|\])/gi, (match, p1) => {
    return `<span class="page-badge"><span class="badge-icon">📄</span> Page ${p1}</span>`;
  });
  try {
    return marked.parse(processed);
  } catch {
    return content;
  }
}

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const SUPPORTED_NLLB_LANGUAGES = [
  { language: "English", nllb_code: "eng_Latn", flag: "🇺🇸", native_name: "English" },
  { language: "Japanese", nllb_code: "jpn_Jpan", flag: "🇯🇵", native_name: "日本語" },
  { language: "Chinese", nllb_code: "zho_Hans", flag: "🇨🇳", native_name: "中文" },
  { language: "German", nllb_code: "deu_Latn", flag: "🇩🇪", native_name: "Deutsch" },
  { language: "French", nllb_code: "fra_Latn", flag: "🇫🇷", native_name: "Français" },
  { language: "Spanish", nllb_code: "spa_Latn", flag: "🇪🇸", native_name: "Español" },
  { language: "Korean", nllb_code: "kor_Hang", flag: "🇰🇷", native_name: "한국어" },
  { language: "Portuguese", nllb_code: "por_Latn", flag: "🇵🇹", native_name: "Português" },
  { language: "Italian", nllb_code: "ita_Latn", flag: "🇮🇹", native_name: "Italiano" },
  { language: "Dutch", nllb_code: "nld_Latn", flag: "🇳🇱", native_name: "Nederlands" },
  { language: "Russian", nllb_code: "rus_Cyrl", flag: "🇷🇺", native_name: "Русский" },
  { language: "Arabic", nllb_code: "arb_Arab", flag: "🇸🇦", native_name: "العربية" },
  { language: "Hindi", nllb_code: "hin_Deva", flag: "🇮🇳", native_name: "हिन्दी" },
];

function getLangMeta(langName) {
  if (!langName) return SUPPORTED_NLLB_LANGUAGES[0];
  const found = SUPPORTED_NLLB_LANGUAGES.find(
    (l) => l.language.toLowerCase() === String(langName).toLowerCase()
  );
  return found || { language: langName, nllb_code: "eng_Latn", flag: "🌐", native_name: langName };
}

const UPLOAD_PIPELINE_STEPS = [
  {
    emoji: "🌐",
    title: "Language Detection",
    subtitle: "Source language & original backup",
    detail: "Preserving untouched original SOP PDF & detecting source language...",
  },
  {
    emoji: "🔤",
    title: "NLLB-200 Translation",
    subtitle: "Canonical English normalization",
    detail: "Translating non-English SOPs to canonical English via NLLB-200 for internal AI processing...",
  },
  {
    emoji: "🧩",
    title: "Vector Store Indexing",
    subtitle: "Azure Text-Embedding-3",
    detail: "Chunking canonical English text & indexing Azure text-embedding-3 semantic vectors...",
  },
  {
    emoji: "📊",
    title: "Compliance Audit",
    subtitle: "Template, Readability & Quality",
    detail: "Benchmarking canonical English representation against Kenvue standards...",
  },
];

const OPTIMIZE_PIPELINE_STEPS = [
  {
    emoji: "📜",
    title: "Skill Directive",
    subtitle: "Canonical English processing",
    detail: "Compiling dynamic optimization skill directives on canonical English representation...",
  },
  {
    emoji: "⚙️",
    title: "Standardization",
    subtitle: "Kenvue 10-tier procedure format",
    detail: "Restructuring sections, standardized safety callouts, and step actions in English...",
  },
  {
    emoji: "🛡️",
    title: "QA Validation Loop",
    subtitle: "Automated agent remediation",
    detail: "Reconciling source evidence and identifying unresolved items for author review...",
  },
  {
    emoji: "🌐",
    title: "NLLB Target Output",
    subtitle: "Output language & ReportLab PDF",
    detail: "Generating final SOP in target output language with original figures & tables re-embedded...",
  },
  {
    emoji: "🔄",
    title: "Vector Re-Indexing",
    subtitle: "Canonical English refresh",
    detail: "Re-indexing canonical English SOP representation into vector store...",
  },
];

const HARMONIZE_PIPELINE_STEPS = [
  {
    emoji: "🔍",
    title: "Semantic Analysis",
    subtitle: "Semantic Similarity & Type Alignment",
    detail: "Comparing canonical English representations & discovering SOP types via Azure text-embedding-3...",
  },
  {
    emoji: "⚖️",
    title: "Conflict Resolution",
    subtitle: "Conservative GMP standards",
    detail: "Resolving operating parameter conflicts (speed, temp, pressure) and standardizing terminology...",
  },
  {
    emoji: "📋",
    title: "Template Alignment",
    subtitle: "Kenvue 10-Tier SOP Structure",
    detail: "Synthesizing unified 10-tier canonical English procedure & preserving unique safety rules...",
  },
  {
    emoji: "🌐",
    title: "NLLB Target Generation",
    subtitle: "Selected output language PDF",
    detail: "Translating harmonized procedure to selected output language & compiling ReportLab PDF...",
  },
];

function PipelineProgressBar({ mode, progress, currentStageIndex, stageDetail, title, badgeText, customSteps }) {
  const steps = customSteps || (mode === "upload" ? UPLOAD_PIPELINE_STEPS : OPTIMIZE_PIPELINE_STEPS);
  const gridClass = steps.length === 4 ? "steps-4" : "steps-5";
  const displayPct = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div className="pipeline-container">
      <div className="pipeline-header">
        <div className="pipeline-title-group">
          <div className="pipeline-pulse-badge">
            <span className="pipeline-pulse-dot" />
            <span>{badgeText || (mode === "upload" ? "AUDIT & EVALUATION PIPELINE" : "OPTIMIZATION & RE-INDEXING PIPELINE")}</span>
          </div>
          <h3 className="pipeline-main-title">{title}</h3>
        </div>
        <div className="pipeline-percentage-box">
          <span className="pipeline-pct-number">{displayPct}%</span>
          <span className="pipeline-pct-label">PROGRESS</span>
        </div>
      </div>

      <div className="pipeline-bar-track">
        <div className="pipeline-bar-fill" style={{ width: `${Math.min(100, Math.max(3, displayPct))}%` }}>
          <div className="pipeline-bar-shimmer" />
          <div className="pipeline-bar-glow" />
        </div>
      </div>

      <div className={`pipeline-steps-grid ${gridClass}`}>
        {steps.map((step, idx) => {
          let status = "step-pending";
          if (progress >= 100 || idx < currentStageIndex) {
            status = "step-done";
          } else if (idx === currentStageIndex) {
            status = "step-active";
          }

          return (
            <div key={idx} className={`pipeline-step-item ${status}`}>
              <div className="pipeline-step-node">
                {status === "step-done" ? (
                  "✓"
                ) : status === "step-active" ? (
                  <div className="step-spinner-node" />
                ) : (
                  idx + 1
                )}
              </div>
              <div className="pipeline-step-content">
                <div className="pipeline-step-title">
                  <span className="step-emoji">{step.emoji}</span>
                  <span>{step.title}</span>
                </div>
                <div className="pipeline-step-subtitle">{step.subtitle}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="pipeline-live-ticker">
        <span className="ticker-pulse-icon">⚡</span>
        <div className="ticker-text-wrapper">
          <span className="ticker-prefix">CURRENT BACKEND OPERATION</span>
          <span className="ticker-message">{stageDetail || steps[currentStageIndex]?.detail || "Processing..."}</span>
        </div>
      </div>
    </div>
  );
}

function LlmErrorBanner({ message, onDismiss, onOpenSettings, isAdmin }) {
  if (!message) return null;
  const isLlmDown =
    /llm|unavailable|unreachable|api key|rate.?limit|quota|provider|connection/i.test(message);

  return (
    <div
      style={{
        margin: "12px 0",
        padding: "14px 16px",
        borderRadius: "10px",
        background: "#fef2f2",
        border: "1px solid #fecaca",
        color: "#991b1b",
        textAlign: "left",
        boxShadow: "0 2px 8px rgba(220, 38, 38, 0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "12px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
          <span style={{ fontSize: "18px", lineHeight: 1.2 }}>{isLlmDown ? "🔌" : "⚠️"}</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: "13.5px", color: "#7f1d1d", marginBottom: "4px" }}>
              {isLlmDown ? "LLM Service Unavailable (Chat & SOP Actions Locked)" : "Operation Could Not Be Completed"}
            </div>
            <div style={{ fontSize: "12.5px", lineHeight: 1.5, color: "#991b1b" }}>{message}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "8px" }}>
              {isLlmDown && isAdmin && onOpenSettings && (
                <button
                  type="button"
                  onClick={onOpenSettings}
                  style={{
                    padding: "5px 11px",
                    borderRadius: "6px",
                    border: "1px solid #fca5a5",
                    background: "#ffffff",
                    color: "#b91c1c",
                    fontSize: "12px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  ⚙️ Configure LLM Provider / API Key
                </button>
              )}
              {onDismiss && (
                <button
                  type="button"
                  onClick={onDismiss}
                  style={{
                    padding: "5px 11px",
                    borderRadius: "6px",
                    border: "1px solid #fca5a5",
                    background: "#fee2e2",
                    color: "#991b1b",
                    fontSize: "12px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  🔄 Dismiss &amp; Retry LLM Connection
                </button>
              )}
            </div>
          </div>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            style={{
              background: "transparent",
              border: "none",
              color: "#b91c1c",
              fontSize: "14px",
              fontWeight: 700,
              cursor: "pointer",
              padding: "2px 6px",
            }}
            title="Dismiss alert"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

function App() {
  // Auth state
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const saved = localStorage.getItem("sop_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [authMode, setAuthMode] = useState("login"); // 'login' or 'register'
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");

  // Chats & messaging
  const [chats, setChats] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  // SOP & Evaluation state
  const [activeSop, setActiveSop] = useState(null);
  const [artifacts, setArtifacts] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStageIndex, setUploadStageIndex] = useState(0);
  const [uploadStageDetail, setUploadStageDetail] = useState("");
  const [selectedDocId, setSelectedDocId] = useState("all");

  // Optimization workflow state
  const [showOptForm, setShowOptForm] = useState(false);
  const [selectedSuggestions, setSelectedSuggestions] = useState([]);
  const [customInstructions, setCustomInstructions] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const [optStatus, setOptStatus] = useState("");
  const [optError, setOptError] = useState("");
  const [optResult, setOptResult] = useState(null);
  const [optProgress, setOptProgress] = useState(0);
  const [optStageIndex, setOptStageIndex] = useState(0);
  const [optStageDetail, setOptStageDetail] = useState("");

  // Modals & previews
  const [artifactsModalOpen, setArtifactsModalOpen] = useState(false);
  const [artifactFilter, setArtifactFilter] = useState("all");
  const [pdfPreviewOpen, setPdfPreviewOpen] = useState(false);
  const [pdfPreviewTitle, setPdfPreviewTitle] = useState("");
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState("");

  // Multi-SOP Similarity & Harmonization state
  const [similarityData, setSimilarityData] = useState(null);
  const [selectedHarmonizeIds, setSelectedHarmonizeIds] = useState([]);
  const [harmonizing, setHarmonizing] = useState(false);
  const [harmonizeError, setHarmonizeError] = useState("");
  const [showOverlapDetails, setShowOverlapDetails] = useState(false);
  const [harmonizedVersions, setHarmonizedVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState(null);
  const [harmProgress, setHarmProgress] = useState(0);
  const [harmStageIndex, setHarmStageIndex] = useState(0);
  const [harmStageDetail, setHarmStageDetail] = useState("");

  // Simplification state
  const [simplificationCatalog, setSimplificationCatalog] = useState([]);
  const [showSimplifyPanel, setShowSimplifyPanel] = useState(false);
  const [selectedSimpRecs, setSelectedSimpRecs] = useState([]);
  const [simplifying, setSimplifying] = useState(false);
  const [simplifyError, setSimplifyError] = useState("");

  // Interactive Refinement state
  const [refinementPrompt, setRefinementPrompt] = useState("");
  const [refining, setRefining] = useState(false);
  const [refineError, setRefineError] = useState("");

  // Multilingual & NLLB Output Language state
  const [singleSopOutputLanguage, setSingleSopOutputLanguage] = useState("English");
  const [selectedHarmonizeLanguage, setSelectedHarmonizeLanguage] = useState("English");
  const [settingDocLanguage, setSettingDocLanguage] = useState(false);

  // Admin template upload state
  const [templateFile, setTemplateFile] = useState(null);
  const [templateUploading, setTemplateUploading] = useState(false);
  const [templateUploadMsg, setTemplateUploadMsg] = useState("");

  const fileInputRef = useRef(null);
  const templateInputRef = useRef(null);

  const [settings, setSettings] = useState({
    provider: "azure_openai",
    model: "",
    azureConfigured: false,
    azureOpenaiEndpoint: "",
    azureOpenaiKey: "",
    azureOpenaiMaskedKey: "",
    azureOpenaiDeploymentName: "",
    azureOpenaiEmbeddingDeployment: "text-embedding-3-small",
    azureOpenaiApiVersion: "2024-02-01",
    configured: true,
    loaded: false,
    activeMaskedKey: "",
    envFilePath: ".env",
    template_status: null,
  });
  const [settingsSaveMsg, setSettingsSaveMsg] = useState("");

  const isLlmUnavailableText = (msg) =>
    Boolean(msg && /llm|unavailable|unreachable|api key|rate.?limit|quota|provider|connection|azure/i.test(msg));

  const activeLlmUnavailableError =
    [chatError, uploadError, optError, harmonizeError, simplifyError, refineError].find(isLlmUnavailableText) ||
    (settings.loaded && !settings.configured
      ? "LLM Service Unavailable: Azure OpenAI is not configured. Open Admin Settings to configure Azure credentials."
      : "");

  const clearAllLlmErrors = () => {
    setChatError("");
    if (isLlmUnavailableText(uploadError)) setUploadError("");
    if (isLlmUnavailableText(optError)) setOptError("");
    if (isLlmUnavailableText(harmonizeError)) setHarmonizeError("");
    if (isLlmUnavailableText(simplifyError)) setSimplifyError("");
    if (isLlmUnavailableText(refineError)) setRefineError("");
  };

  const getHeaders = () => ({
    "Content-Type": "application/json",
    "X-User-Name": currentUser?.username || "admin",
  });

  // Load conversations and settings
  const load = async () => {
    if (!currentUser) return;
    try {
      const [c, s] = await Promise.all([
        fetch(`${API}/conversations`, { headers: { "X-User-Name": currentUser.username } }).then((r) => r.json()),
        fetch(`${API}/settings`).then((r) => r.json()),
      ]);
      setChats(Array.isArray(c) ? c : []);
      setSettings((x) => ({
        ...x,
        provider: s.provider || "azure_openai",
        model: s.model || "",
        azureConfigured: Boolean(s.azure_configured),
        azureOpenaiEndpoint: s.azure_openai_endpoint || "",
        azureOpenaiMaskedKey: s.azure_openai_masked_key || "",
        azureOpenaiDeploymentName: s.azure_openai_deployment_name || "",
        azureOpenaiEmbeddingDeployment: s.azure_openai_embedding_deployment || "text-embedding-3-small",
        azureOpenaiApiVersion: s.azure_openai_api_version || "2024-02-01",
        configured: Boolean(s.api_key_configured ?? s.azure_configured),
        loaded: true,
        activeMaskedKey: s.active_masked_key || s.azure_openai_masked_key || "",
        envFilePath: s.env_file_path || ".env",
        template_status: s.template_status,
      }));
    } catch (e) {
      console.error("Failed to load initial data:", e);
    }
  };

  useEffect(() => {
    if (currentUser) {
      load();
    }
  }, [currentUser]);

  // Auth Handlers
  const handleAuth = async (e) => {
    if (e) e.preventDefault();
    setAuthError("");
    const endpoint = authMode === "login" ? `${API}/auth/login` : `${API}/auth/register`;
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: authUsername.trim(), password: authPassword }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed");
      const userObj = { username: data.username, role: data.role };
      setCurrentUser(userObj);
      localStorage.setItem("sop_user", JSON.stringify(userObj));
      setAuthPassword("");
    } catch (err) {
      setAuthError(err.message);
    }
  };

  const handleLogout = () => {
    setCurrentUser(null);
    localStorage.removeItem("sop_user");
    setActive(null);
    setChats([]);
    setMessages([]);
    setActiveSop(null);
    setOptResult(null);
    setSettingsOpen(false);
  };

  // Load active SOP data
  const loadSopInfo = async (conversationId) => {
    try {
      const [sopRes, artRes] = await Promise.all([
        fetch(`${API}/conversations/${conversationId}/sop`).then((r) => r.json()),
        fetch(`${API}/conversations/${conversationId}/artifacts`).then((r) => r.json()),
      ]);
      if (sopRes.has_sop) {
        setActiveSop(sopRes);
        const docs = sopRes.documents || [sopRes.document];
        let currentTargetId = selectedDocId;

        if (docs.length > 1) {
          if (selectedDocId !== "all" && !docs.some((d) => d.id === selectedDocId)) {
            currentTargetId = "all";
            setSelectedDocId("all");
          }
        } else if (sopRes.document) {
          currentTargetId = sopRes.document.id;
          setSelectedDocId(sopRes.document.id);
        }

        const targetDoc = (currentTargetId !== "all" && docs.find((d) => d.id === currentTargetId)) || sopRes.document;

        if (targetDoc) {
          setSingleSopOutputLanguage(
            targetDoc.output_language || targetDoc.detected_language || targetDoc.original_language || "English"
          );
        }

        // Compute unique deduplicated languages across uploaded SOPs
        const uniqueLangs = [];
        const seenLangSet = new Set();
        (sopRes.detected_languages || []).forEach((l) => {
          if (l?.language && !seenLangSet.has(l.language)) {
            seenLangSet.add(l.language);
            uniqueLangs.push(l.language);
          }
        });
        docs.forEach((d) => {
          const lName = d?.detected_language || d?.original_language || "English";
          if (lName && !seenLangSet.has(lName)) {
            seenLangSet.add(lName);
            uniqueLangs.push(lName);
          }
        });
        if (uniqueLangs.length === 0) uniqueLangs.push("English");
        setSelectedHarmonizeLanguage((prev) =>
          uniqueLangs.includes(prev) ? prev : uniqueLangs[0]
        );

        if (targetDoc?.optimized_scores?.suggestions) {
          setSelectedSuggestions(targetDoc.optimized_scores.suggestions.map((s) => s.id));
        } else if (targetDoc?.scores?.suggestions) {
          // Pre-select all suggestions by default
          setSelectedSuggestions(targetDoc.scores.suggestions.map((s) => s.id));
        }

        if (currentTargetId !== "all" && targetDoc && (targetDoc.optimized_scores || targetDoc.optimization_report)) {
          const rep = targetDoc.optimization_report || {};
          setOptResult({
            document_id: targetDoc.id,
            document_title: targetDoc.optimized_title || rep.document_title || targetDoc.filename,
            title: targetDoc.optimized_title || rep.document_title || targetDoc.filename,
            previous_scores: rep.previous_scores || targetDoc.scores,
            updated_scores: targetDoc.optimized_scores || rep.updated_scores,
            output_language: targetDoc.output_language || rep.output_language || targetDoc.detected_language || "English",
            detected_language: targetDoc.detected_language || rep.detected_language || "English",
            internal_processing_language: "English",
            before_and_after_comparison: rep.before_and_after_comparison,
            score_difference: rep.score_difference ?? (targetDoc.optimized_scores && targetDoc.scores ? (targetDoc.optimized_scores.average_score - targetDoc.scores.average_score) : 0),
            resolved_violations: rep.resolved_violations || [],
            newly_introduced_violations: rep.newly_introduced_violations || [],
            validation_report: rep.validation_report,
            summary: rep.summary || "Optimized SOP generated according to Kenvue standards.",
            pdf_download_url: `/conversations/${conversationId}/optimized-sop/download?document_id=${targetDoc.id}`,
            pdf_preview_url: `/conversations/${conversationId}/optimized-sop/preview?document_id=${targetDoc.id}`,
            skill_url: `/conversations/${conversationId}/optimization-skill?document_id=${targetDoc.id}`,
          });
        } else if (currentTargetId === "all") {
          setOptResult(null);
        }
        setSimilarityData(sopRes.similarity_analysis || null);
        const harmVers = sopRes.harmonized_versions || [];
        setHarmonizedVersions(harmVers);
        if (harmVers.length > 0) {
          setSelectedVersionId(sopRes.latest_harmonized_version?.id || harmVers[harmVers.length - 1].id);
        } else {
          setSelectedVersionId(null);
        }

        if (sopRes.similarity_analysis?.recommended_harmonize_ids?.length) {
          setSelectedHarmonizeIds(sopRes.similarity_analysis.recommended_harmonize_ids);
        } else if (sopRes.documents?.length) {
          setSelectedHarmonizeIds(sopRes.documents.map((d) => d.id));
        }

        fetch(`${API}/conversations/${conversationId}/harmonized-sop/simplification-suggestions`)
          .then((r) => r.json())
          .then((data) => {
            if (data.catalog) {
              setSimplificationCatalog(data.catalog);
              setSelectedSimpRecs(data.catalog.map((c) => c.id));
            }
          })
          .catch(() => {});
      } else {
        setActiveSop(null);
        setSelectedDocId("all");
        setSimilarityData(null);
        setHarmonizedVersions([]);
        setSelectedVersionId(null);
      }
      setArtifacts(Array.isArray(artRes) ? artRes : []);
    } catch (e) {
      console.error("Error loading SOP data:", e);
      setActiveSop(null);
      setArtifacts([]);
      setSimilarityData(null);
      setHarmonizedVersions([]);
      setSelectedVersionId(null);
    }
  };

  // Manual Source Language Override / Re-Translation Handler
  const handleSetDocumentLanguage = async (docId, newLanguage) => {
    if (!active || !docId || !newLanguage) return;
    setSettingDocLanguage(true);
    try {
      const res = await fetch(`${API}/conversations/${active.id}/sop/${docId}/set-language`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ language: newLanguage }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to update language");
      setSingleSopOutputLanguage(newLanguage);
      await loadSopInfo(active.id);
    } catch (err) {
      alert(`Language update error: ${err.message}`);
    } finally {
      setSettingDocLanguage(false);
    }
  };

  const newChat = async () => {
    try {
      const r = await fetch(`${API}/conversations`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ title: "New Chat" }),
      });
      const chat = await r.json();
      setChats((x) => [chat, ...x]);
      setActive(chat);
      setMessages([]);
      setActiveSop(null);
      setSelectedDocId("all");
      setArtifacts([]);
      setOptResult(null);
      setOptError("");
      setShowOptForm(false);
      setUploadError("");
      setChatError("");
      setSettingsOpen(false);
      setSimilarityData(null);
      setSelectedHarmonizeIds([]);
      setHarmonizing(false);
      setHarmonizeError("");
      setHarmonizedVersions([]);
      setSelectedVersionId(null);
      setShowSimplifyPanel(false);
      setSimplifyError("");
      setRefinementPrompt("");
      setRefineError("");
      setSingleSopOutputLanguage("English");
      setSelectedHarmonizeLanguage("English");
    } catch (e) {
      console.error("Failed to create conversation:", e);
    }
  };

  const openChat = async (chat) => {
    setActive(chat);
    setSettingsOpen(false);
    setUploadError("");
    setChatError("");
    setOptError("");
    setOptResult(null);
    setShowOptForm(false);
    setSimilarityData(null);
    setSelectedHarmonizeIds([]);
    setHarmonizing(false);
    setHarmonizeError("");
    setHarmonizedVersions([]);
    setSelectedVersionId(null);
    setShowSimplifyPanel(false);
    setSimplifyError("");
    setRefinementPrompt("");
    setRefineError("");
    try {
      const msgs = await fetch(`${API}/conversations/${chat.id}/messages`).then((r) => r.json());
      setMessages(msgs);
      await loadSopInfo(chat.id);
    } catch (e) {
      console.error("Error opening chat:", e);
    }
  };

  const handleDeleteChat = async (e, chat) => {
    e.stopPropagation();
    const confirmed = window.confirm(
      `Are you sure you want to permanently delete "${chat.title}"?\n\nThis will permanently wipe all conversation messages, SOP documents, vector embeddings, and storage summaries.`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`${API}/conversations/${chat.id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to delete chat session");
      }

      const updatedChats = chats.filter((c) => c.id !== chat.id);
      setChats(updatedChats);

      if (active?.id === chat.id) {
        if (updatedChats.length > 0) {
          openChat(updatedChats[0]);
        } else {
          newChat();
        }
      }
    } catch (err) {
      console.error("Error deleting conversation:", err);
      alert(`Could not delete session: ${err.message}`);
    }
  };

  // SOP Upload & Evaluation (Supports up to 10 SOP PDFs)
  const handleFileUpload = async (filesInput) => {
    if (!filesInput || !active) return;
    const rawFiles = filesInput instanceof FileList
      ? Array.from(filesInput)
      : Array.isArray(filesInput)
      ? filesInput
      : [filesInput];

    if (rawFiles.length === 0) return;

    if (rawFiles.length > 10) {
      setUploadError(`Maximum 10 SOP documents allowed at a time (you selected ${rawFiles.length}). Please choose up to 10 files.`);
      return;
    }

    const invalidFile = rawFiles.find((f) => {
      const name = (f.name || "").toLowerCase();
      return !name.endsWith(".pdf") && !name.endsWith(".docx");
    });
    if (invalidFile) {
      setUploadError(`All files must be valid PDF or DOCX documents (.pdf, .docx). Found: ${invalidFile.name}`);
      return;
    }

    setUploading(true);
    setUploadError("");
    setChatError("");
    setUploadProgress(4);
    setUploadStageIndex(0);
    const count = rawFiles.length;
    setUploadStageDetail(
      count > 1
        ? `Preserving ${count} untouched original SOP documents (PDF/DOCX) & detecting source languages...`
        : UPLOAD_PIPELINE_STEPS[0].detail
    );

    const formData = new FormData();
    rawFiles.forEach((f) => {
      formData.append("files", f);
    });
    // Compatibility fallback
    formData.append("file", rawFiles[0]);

    const startTime = Date.now();
    const progressTimer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      let nextPct = 4;
      let stage = 0;

      if (elapsed < 1400) {
        nextPct = 4 + (elapsed / 1400) * 20;
        stage = 0;
      } else if (elapsed < 2800) {
        nextPct = 25 + ((elapsed - 1400) / 1400) * 24;
        stage = 1;
      } else if (elapsed < 4400) {
        nextPct = 50 + ((elapsed - 2800) / 1600) * 24;
        stage = 2;
      } else {
        const extra = Math.min(19, ((elapsed - 4400) / 3500) * 19);
        nextPct = 75 + extra;
        stage = 3;
      }

      setUploadProgress(Math.min(94, Math.round(nextPct)));
      setUploadStageIndex(stage);
      if (stage === 1 && count > 1) {
        setUploadStageDetail(`Translating non-English SOPs across ${count} documents to canonical English via NLLB-200...`);
      } else if (stage === 2 && count > 1) {
        setUploadStageDetail(`Generating Azure text-embedding-3 embeddings on canonical English & discovering semantic clusters for ${count} SOPs...`);
      } else if (stage === 3 && count > 1) {
        setUploadStageDetail(`Auditing canonical English representations across all ${count} SOP documents & compiling scorecards...`);
      } else {
        setUploadStageDetail(UPLOAD_PIPELINE_STEPS[stage]?.detail || "");
      }
    }, 100);

    try {
      const res = await fetch(`${API}/conversations/${active.id}/upload-sop`, {
        method: "POST",
        headers: { "X-User-Name": currentUser.username },
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");

      clearAllLlmErrors();
      clearInterval(progressTimer);
      setUploadProgress(100);
      setUploadStageIndex(UPLOAD_PIPELINE_STEPS.length - 1);
      setUploadStageDetail("Multilingual NLLB normalization, semantic type discovery & audit complete!");

      // Brief delay to showcase 100% completion
      await new Promise((r) => setTimeout(r, 450));

      await loadSopInfo(active.id);

      if (data.conversation_title) {
        setActive((prev) => ({ ...prev, title: data.conversation_title }));
        setChats((prev) =>
          prev.map((c) => (c.id === active.id ? { ...c, title: data.conversation_title } : c))
        );
      }
    } catch (e) {
      clearInterval(progressTimer);
      setUploadError(e.message || "Failed to process SOP PDFs.");
    } finally {
      clearInterval(progressTimer);
      setUploading(false);
      setUploadProgress(0);
      setUploadStageIndex(0);
      setUploadStageDetail("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Optimization Execution (Automatically outputs in the uploaded SOP's detected language)
  const handleOptimize = async () => {
    if (!active || !activeSop) return;
    const targetDoc = (selectedDocId !== "all" && activeSop?.documents?.find((d) => d.id === selectedDocId)) || activeSop.document;
    const chosenOutputLang = targetDoc?.detected_language || targetDoc?.original_language || "English";

    setOptimizing(true);
    setOptError("");
    setChatError("");
    setOptProgress(3);
    setOptStageIndex(0);
    setOptStageDetail(OPTIMIZE_PIPELINE_STEPS[0].detail);

    const startTime = Date.now();
    const progressTimer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      let nextPct = 3;
      let stage = 0;

      if (elapsed < 1800) {
        nextPct = 3 + (elapsed / 1800) * 16;
        stage = 0;
      } else if (elapsed < 4200) {
        nextPct = 20 + ((elapsed - 1800) / 2400) * 24;
        stage = 1;
      } else if (elapsed < 7500) {
        nextPct = 45 + ((elapsed - 4200) / 3300) * 24;
        stage = 2;
      } else if (elapsed < 10500) {
        nextPct = 70 + ((elapsed - 7500) / 3000) * 19;
        stage = 3;
      } else {
        const extra = Math.min(6, ((elapsed - 10500) / 4000) * 6);
        nextPct = 90 + extra;
        stage = 4;
      }

      setOptProgress(Math.min(96, Math.round(nextPct)));
      setOptStageIndex(stage);
      setOptStageDetail(OPTIMIZE_PIPELINE_STEPS[stage]?.detail || "");
    }, 120);

    try {
      const res = await fetch(`${API}/conversations/${active.id}/optimize-sop`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          selected_suggestion_ids: selectedSuggestions,
          custom_instructions: customInstructions,
          document_id: targetDoc?.id,
          output_language: chosenOutputLang,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Optimization failed");

      clearAllLlmErrors();
      clearInterval(progressTimer);
      setOptProgress(100);
      setOptStageIndex(OPTIMIZE_PIPELINE_STEPS.length - 1);
      setOptStageDetail(`Standardization in ${data.output_language || chosenOutputLang} and vector re-indexing complete!`);

      // Brief delay to showcase 100% completion
      await new Promise((r) => setTimeout(r, 600));

      setOptResult({
        ...data,
        document_id: targetDoc?.id,
        output_language: data.output_language || chosenOutputLang,
        detected_language: data.detected_language || targetDoc?.detected_language || "English",
        internal_processing_language: "English",
        pdf_download_url: `/conversations/${active.id}/optimized-sop/download?document_id=${targetDoc?.id || data.document_id}`,
        pdf_preview_url: `/conversations/${active.id}/optimized-sop/preview?document_id=${targetDoc?.id || data.document_id}`,
        skill_url: `/conversations/${active.id}/optimization-skill?document_id=${targetDoc?.id || data.document_id}`,
      });
      setShowOptForm(false);
      await loadSopInfo(active.id);

      // Add assistant confirmation message in chat
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `✨ **SOP "${targetDoc?.filename || "Document"}" Optimization Draft Generated — Author Review Required**\n\n` +
            `• **Detected Source Language**: ${targetDoc?.detected_language || "English"} (${targetDoc?.nllb_language_code || "eng_Latn"})\n` +
            `• **Internal Processing Language**: English (Canonical NLLB-200 Representation)\n` +
            `• **Generated Output Language**: **${data.output_language || chosenOutputLang}**\n` +
            `• **Compliance Score**: Raised from **${data.previous_scores?.average_score || 70}%** to **${data.updated_scores.average_score}%** (+${data.updated_scores.average_score - (data.previous_scores?.average_score || 70)} pts)\n` +
            `• **Original Document Preserved**: The original uploaded SOP in ${targetDoc?.original_language || targetDoc?.detected_language || "English"} remains untouched and available.\n\n` +
            `You can download or preview your optimized PDF above, view the original SOP, continue asking questions, or click **End Chat** when finished.`,
        },
      ]);
    } catch (e) {
      clearInterval(progressTimer);
      setOptError(e.message || "LLM Service Unavailable: Could not optimize SOP.");
    } finally {
      clearInterval(progressTimer);
      setOptimizing(false);
      setOptProgress(0);
      setOptStageIndex(0);
      setOptStageDetail("");
    }
  };

  // Multi-SOP Harmonization Execution
  const handleHarmonize = async () => {
    if (!active || selectedHarmonizeIds.length < 2) return;
    if (!selectedHarmonizeLanguage) {
      setHarmonizeError("Please select an output language for the harmonized SOP.");
      return;
    }
    setHarmonizing(true);
    setHarmonizeError("");
    setChatError("");
    setHarmProgress(5);
    setHarmStageIndex(0);
    setHarmStageDetail(HARMONIZE_PIPELINE_STEPS[0].detail);

    const startTime = Date.now();
    const progressTimer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      let nextPct = 5;
      let stage = 0;
      if (elapsed < 1500) {
        nextPct = 5 + (elapsed / 1500) * 25;
        stage = 0;
      } else if (elapsed < 3500) {
        nextPct = 30 + ((elapsed - 1500) / 2000) * 30;
        stage = 1;
      } else if (elapsed < 6000) {
        nextPct = 60 + ((elapsed - 3500) / 2500) * 25;
        stage = 2;
      } else {
        const extra = Math.min(10, ((elapsed - 6000) / 3000) * 10);
        nextPct = 85 + extra;
        stage = 3;
      }
      setHarmProgress(Math.min(96, Math.round(nextPct)));
      setHarmStageIndex(stage);
      setHarmStageDetail(HARMONIZE_PIPELINE_STEPS[stage]?.detail || "");
    }, 120);

    try {
      const res = await fetch(`${API}/conversations/${active.id}/harmonize-sops`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          selected_document_ids: selectedHarmonizeIds,
          custom_instructions: customInstructions,
          output_language: selectedHarmonizeLanguage,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Harmonization failed");

      clearAllLlmErrors();
      clearInterval(progressTimer);
      setHarmProgress(100);
      setHarmStageIndex(HARMONIZE_PIPELINE_STEPS.length - 1);
      setHarmStageDetail(`Consolidation, Kenvue 10-tier alignment & ${data.output_language || selectedHarmonizeLanguage} PDF compilation complete!`);

      await new Promise((r) => setTimeout(r, 600));

      await loadSopInfo(active.id);
      setSelectedVersionId(data.id);
      setShowSimplifyPanel(false);
      setCustomInstructions("");

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `✨ **Harmonized SOP Successfully Generated in ${data.output_language || selectedHarmonizeLanguage}!**\n\n` +
            `• **Consolidated Document**: ${data.title}\n` +
            `• **Version**: ${data.version_label}\n` +
            `• **Detected Source Languages**: ${(data.detected_languages || []).join(", ") || "English"}\n` +
            `• **Internal Processing Language**: English (Canonical NLLB-200 Representation)\n` +
            `• **Selected Output Language**: **${data.output_language || selectedHarmonizeLanguage}**\n` +
            `• **Source Lineage**: ${data.source_filenames?.join(", ")}\n` +
            `• **Overall Quality Score**: **${data.scores?.average_score}%** (Template: ${data.scores?.template_score}%, Readability: ${data.scores?.readability_score}%, Quality: ${data.scores?.quality_score}%)\n` +
            `• **Status**: All conflicting parameters resolved to GMP limits and unified into Kenvue 10-tier procedure format.`,
        },
      ]);
    } catch (e) {
      clearInterval(progressTimer);
      setHarmonizeError(e.message || "Failed to harmonize SOPs");
    } finally {
      clearInterval(progressTimer);
      setHarmonizing(false);
      setHarmProgress(0);
      setHarmStageIndex(0);
      setHarmStageDetail("");
    }
  };

  // Simplification Recommendation Execution
  const handleSimplify = async () => {
    if (!active) return;
    setSimplifying(true);
    setSimplifyError("");
    setChatError("");
    const targetOutLang = activeHarmonizedVersion?.output_language || selectedHarmonizeLanguage || "English";
    try {
      const recsToApply = selectedSimpRecs.length > 0 ? selectedSimpRecs : simplificationCatalog.map((c) => c.id);
      const res = await fetch(`${API}/conversations/${active.id}/harmonized-sop/simplify`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          version_id: selectedVersionId,
          selected_recommendation_ids: recsToApply,
          output_language: targetOutLang,
        }),
      });

      const newVersion = await res.json();
      if (!res.ok) throw new Error(newVersion.detail || "Simplification failed");

      clearAllLlmErrors();
      await loadSopInfo(active.id);
      setSelectedVersionId(newVersion.id);
      setShowSimplifyPanel(false);

      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `⚡ **Harmonized SOP v${newVersion.version_number} (Simplified in ${newVersion.output_language || targetOutLang}) Created!**\n\n` +
            `• **Output Language**: **${newVersion.output_language || targetOutLang}** (Internal Processing: English)\n` +
            `• **Readability Score**: Improved to **${newVersion.scores?.readability_score}%**\n` +
            `• **Overall Score**: **${newVersion.scores?.average_score}%**\n` +
            `• **Changes Applied**: ${newVersion.change_summary}\n` +
            `• **Version Preservation**: Previous version v${newVersion.version_number - 1} remains accessible and unchanged.`,
        },
      ]);
    } catch (e) {
      setSimplifyError(e.message || "LLM Service Unavailable: Could not simplify SOP.");
    } finally {
      setSimplifying(false);
    }
  };

  // Interactive Conversational Refinement Execution
  const handleRefine = async (e) => {
    if (e) e.preventDefault();
    if (!active || !refinementPrompt.trim()) return;
    setRefining(true);
    setRefineError("");
    setChatError("");
    const userPromptText = refinementPrompt.trim();
    const targetOutLang = activeHarmonizedVersion?.output_language || selectedHarmonizeLanguage || "English";

    try {
      const res = await fetch(`${API}/conversations/${active.id}/harmonized-sop/refine`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          version_id: selectedVersionId,
          refinement_prompt: userPromptText,
          output_language: targetOutLang,
        }),
      });

      const newVersion = await res.json();
      if (!res.ok) throw new Error(newVersion.detail || "Refinement failed");

      clearAllLlmErrors();
      await loadSopInfo(active.id);
      setSelectedVersionId(newVersion.id);
      setRefinementPrompt("");

      setMessages((m) => [
        ...m,
        { role: "user", content: userPromptText },
        {
          role: "assistant",
          content: `💬 **Refinement Applied! Generated Harmonized SOP v${newVersion.version_number} (${newVersion.output_language || targetOutLang}).**\n\n` +
            `• **Directives Incorporated**: "${userPromptText}"\n` +
            `• **Output Language**: **${newVersion.output_language || targetOutLang}** (Internal Processing: English)\n` +
            `• **Updated Overall Score**: **${newVersion.scores?.average_score}%**\n` +
            `• **Lineage**: Generated from parent version v${newVersion.version_number - 1}. Full historical version trail retained.`,
        },
      ]);
    } catch (e) {
      setRefineError(e.message || "Failed to apply refinement");
    } finally {
      setRefining(false);
    }
  };

  // End Chat & Lifecycle Cleanup
  const handleEndChat = async () => {
    if (!active) return;
    const confirm = window.confirm(
      "Are you sure you want to end this chat? A comprehensive session summary will be archived in MinIO, and temporary image/table assets will be cleaned up."
    );
    if (!confirm) return;

    try {
      const res = await fetch(`${API}/conversations/${active.id}/end-chat`, {
        method: "POST",
        headers: getHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed ending chat");

      alert(`✅ ${data.message}`);
      await newChat();
    } catch (e) {
      alert(`Error ending chat: ${e.message}`);
    }
  };

  // Admin Template Upload Handler
  const handleAdminTemplateUpload = async (e) => {
    e.preventDefault();
    if (!templateFile) return;
    setTemplateUploading(true);
    setTemplateUploadMsg("");

    const formData = new FormData();
    formData.append("file", templateFile);

    try {
      const res = await fetch(`${API}/admin/upload-template`, {
        method: "POST",
        headers: { "X-User-Name": currentUser.username },
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Template upload failed");

      setTemplateUploadMsg(`✅ Successfully updated Kenvue Standard Guideline (${data.chunks_count} rule chunks indexed)!`);
      setTemplateFile(null);
      if (templateInputRef.current) templateInputRef.current.value = "";
      load();
    } catch (err) {
      setTemplateUploadMsg(`❌ Error: ${err.message}`);
    } finally {
      setTemplateUploading(false);
    }
  };

  // Chat message sending
  const send = async () => {
    if (!input.trim() || !active || loading || Boolean(activeLlmUnavailableError)) return;
    const content = input.trim();
    setInput("");
    setChatError("");
    setMessages((m) => [...m, { role: "user", content }]);
    setLoading(true);

    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ conversation_id: active.id, content }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Request failed");

      clearAllLlmErrors();
      setMessages((m) => [...m, data]);

      if (data.title && data.title !== active.title) {
        setActive((prev) => ({ ...prev, title: data.title }));
        setChats((prev) =>
          prev.map((c) => (c.id === active.id ? { ...c, title: data.title } : c))
        );
      }
    } catch (e) {
      const errMsg = e.message || "LLM Service Unavailable: Could not generate a chat response.";
      if (isLlmUnavailableText(errMsg)) {
        // Roll back the optimistic user message so no chat messages appear while the LLM is down
        setMessages((m) => m.slice(0, -1));
        setInput(content);
        setChatError(errMsg);
        if (!activeSop) {
          setUploadError(errMsg);
        }
      } else {
        setMessages((m) => [...m, { role: "assistant", content: `Error: ${errMsg}` }]);
      }
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async () => {
    setSettingsSaveMsg("");
    try {
      const r = await fetch(`${API}/settings`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          azure_openai_endpoint: settings.azureOpenaiEndpoint,
          azure_openai_key: settings.azureOpenaiKey,
          azure_openai_deployment_name: settings.azureOpenaiDeploymentName,
          azure_openai_embedding_deployment: settings.azureOpenaiEmbeddingDeployment,
          azure_openai_api_version: settings.azureOpenaiApiVersion,
        }),
      });
      const data = await r.json();
      if (!r.ok) return alert(data.detail || "Could not save LLM provider settings");
      setSettings((s) => ({ ...s, azureOpenaiKey: "" }));
      clearAllLlmErrors();
      await load();
      setSettingsSaveMsg(
        data.message || "Provider configuration saved."
      );
    } catch (e) {
      alert(`Could not save settings: ${e.message}`);
    }
  };

  // Helper for score badges
  const getScoreBadgeClass = (score) => {
    if (score >= 80) return "green";
    if (score >= 60) return "yellow";
    return "red";
  };

  // If user is not logged in, render Login / Register view
  if (!currentUser) {
    return (
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-brand">
            <h1>KENVUE</h1>
            <span className="brand-badge">SOP AI</span>
          </div>
          <p className="auth-tagline">Standard Operating Procedure Optimization & Audit System</p>

          <div className="auth-tabs">
            <button
              className={`auth-tab ${authMode === "login" ? "active" : ""}`}
              onClick={() => { setAuthMode("login"); setAuthError(""); }}
            >
              Sign In
            </button>
            <button
              className={`auth-tab ${authMode === "register" ? "active" : ""}`}
              onClick={() => { setAuthMode("register"); setAuthError(""); }}
            >
              Create Account
            </button>
          </div>

          <form onSubmit={handleAuth}>
            <div className="auth-input-group">
              <label>Username</label>
              <input
                type="text"
                value={authUsername}
                onChange={(e) => setAuthUsername(e.target.value)}
                placeholder="Enter your username"
                required
              />
            </div>
            <div className="auth-input-group">
              <label>Password</label>
              <input
                type="password"
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                placeholder="Enter password"
                required
              />
            </div>

            {authError && <p style={{ color: "#ef4444", fontSize: "13px", margin: "4px 0 12px" }}>{authError}</p>}

            <button type="submit" className="auth-submit-btn">
              {authMode === "login" ? "Sign In to SOP Portal" : "Create Account & Sign In"}
            </button>
          </form>

          <div className="auth-demo-shortcuts">
            <p>Quick Prototype Access:</p>
            <button
              type="button"
              className="demo-btn"
              onClick={() => { setAuthUsername("admin"); setAuthPassword("admin"); setAuthMode("login"); }}
            >
              🔑 Fill Admin Credentials (admin / admin)
            </button>
            <button
              type="button"
              className="demo-btn"
              onClick={() => { setAuthUsername("operator_1"); setAuthPassword("pass123"); setAuthMode("register"); }}
            >
              👤 Fill New Operator (operator_1 / pass123)
            </button>
          </div>
        </div>
      </div>
    );
  }

  const defaultRefineSuggestions = [
    {
      id: "sug_refine_imperative",
      title: "Streamline Procedural Imperative Phrasing",
      description: "Further polish step directives into direct, crisp imperative commands without auxiliary verbs."
    },
    {
      id: "sug_refine_tolerances",
      title: "Tighten Numerical Tolerances & Critical Limits",
      description: "Verify that all equipment temperatures, speeds, and timing include exact ± ranges."
    },
    {
      id: "sug_refine_safety",
      title: "Enhance Precautionary Warnings & Interlock Checks",
      description: "Ensure personal protective equipment and hazard controls precede mechanical steps."
    },
    {
      id: "sug_refine_qc",
      title: "Sharpen In-Process Quality Acceptance Standards",
      description: "Ensure clear pass/fail checkpoints with documented supervisory sign-offs."
    }
  ];

  const currentDoc = (activeSop?.documents && selectedDocId !== "all")
    ? (activeSop.documents.find((d) => d.id === selectedDocId) || activeSop.document)
    : activeSop?.document;

  const isCollectionOverview = Boolean(activeSop?.documents && activeSop.documents.length > 1 && selectedDocId === "all");

  // Deduplicated unique detected languages across all uploaded SOPs
  const uniqueUploadedLanguages = (() => {
    const docs = activeSop?.documents || (activeSop?.document ? [activeSop.document] : []);
    const map = new Map();
    (activeSop?.detected_languages || []).forEach((item) => {
      if (item?.language && !map.has(item.language)) {
        const meta = getLangMeta(item.language);
        map.set(item.language, {
          language: item.language,
          nllb_code: item.nllb_code || meta.nllb_code,
          flag: item.flag || meta.flag,
          native_name: item.native_name || meta.native_name,
          document_count: item.document_count || 1,
          filenames: item.filenames || [],
        });
      }
    });
    docs.forEach((d) => {
      const lang = d?.detected_language || d?.original_language || "English";
      if (!map.has(lang)) {
        const meta = getLangMeta(lang);
        const matchingDocs = docs.filter((x) => (x?.detected_language || x?.original_language || "English") === lang);
        map.set(lang, {
          language: lang,
          nllb_code: d?.nllb_language_code || meta.nllb_code,
          flag: d?.language_flag || meta.flag,
          native_name: d?.language_native_name || meta.native_name,
          document_count: matchingDocs.length || 1,
          filenames: matchingDocs.map((x) => x.filename),
        });
      }
    });
    if (map.size === 0) {
      map.set("English", { ...SUPPORTED_NLLB_LANGUAGES[0], document_count: 1, filenames: [] });
    }
    return Array.from(map.values());
  })();

  const scores = isCollectionOverview
    ? (activeSop.collection_scores || activeSop.document?.scores)
    : ((currentDoc?.has_optimized_sop || currentDoc?.optimized_scores)
        ? (currentDoc.optimized_scores || currentDoc.scores)
        : currentDoc?.scores);

  const suggestions = (scores?.suggestions && scores.suggestions.length > 0)
    ? scores.suggestions
    : (currentDoc?.scores?.suggestions && currentDoc.scores.suggestions.length > 0)
      ? currentDoc.scores.suggestions
      : ((currentDoc?.has_optimized_sop || currentDoc?.optimized_scores) ? defaultRefineSuggestions : (scores?.suggestions || []));

  const filteredArtifacts = artifacts.filter((a) => (artifactFilter === "all" ? true : a.artifact_type === artifactFilter));

  const activeHarmonizedVersion =
    harmonizedVersions.find((v) => v.id === selectedVersionId) ||
    harmonizedVersions[harmonizedVersions.length - 1] ||
    null;

  const currentDocIndex =
    activeSop?.documents && selectedDocId !== "all"
      ? activeSop.documents.findIndex((d) => d.id === selectedDocId)
      : -1;

  const selectIndividualSop = (doc) => {
    if (!doc) return;
    setSelectedDocId(doc.id);
    setShowOptForm(false);
    setSingleSopOutputLanguage(
      doc.output_language || doc.detected_language || doc.original_language || "English"
    );
    if (doc.optimized_scores || doc.optimization_report) {
      const rep = doc.optimization_report || {};
      setOptResult({
        document_id: doc.id,
        document_title: doc.optimized_title || rep.document_title || doc.filename,
        title: doc.optimized_title || rep.document_title || doc.filename,
        previous_scores: rep.previous_scores || doc.scores,
        updated_scores: doc.optimized_scores || rep.updated_scores,
        output_language: doc.output_language || rep.output_language || doc.detected_language || "English",
        detected_language: doc.detected_language || rep.detected_language || "English",
        internal_processing_language: "English",
        before_and_after_comparison: rep.before_and_after_comparison,
        score_difference: rep.score_difference ?? (doc.optimized_scores && doc.scores ? (doc.optimized_scores.average_score - doc.scores.average_score) : 0),
        resolved_violations: rep.resolved_violations || [],
        newly_introduced_violations: rep.newly_introduced_violations || [],
        validation_report: rep.validation_report,
        summary: rep.summary || "Optimized SOP generated according to Kenvue standards.",
        pdf_download_url: `/conversations/${active.id}/optimized-sop/download?document_id=${doc.id}`,
        pdf_preview_url: `/conversations/${active.id}/optimized-sop/preview?document_id=${doc.id}`,
        skill_url: `/conversations/${active.id}/optimization-skill?document_id=${doc.id}`,
      });
    } else {
      setOptResult(null);
    }
    if (doc.optimized_scores?.suggestions) {
      setSelectedSuggestions(doc.optimized_scores.suggestions.map((s) => s.id));
    } else if (doc.scores?.suggestions) {
      setSelectedSuggestions(doc.scores.suggestions.map((s) => s.id));
    }
  };

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="brand">
          <span>KENVUE SOP</span>
          <span className="brand-badge">PORTAL</span>
        </div>

        <div className="user-badge">
          <span>👤 {currentUser.username}</span>
          <span className="user-role-tag">{currentUser.role}</span>
        </div>

        <button className="new" onClick={newChat}>
          <span>+</span> New Chat
        </button>

        <div className="label">History</div>
        <div className="history">
          {chats.map((c) => (
            <div
              key={c.id}
              className={`historyRow ${active?.id === c.id ? "active" : ""}`}
            >
              <button
                className="historyItem"
                onClick={() => openChat(c)}
                title={c.title}
              >
                {c.title}
              </button>
              <button
                className="historyDeleteBtn"
                onClick={(e) => handleDeleteChat(e, c)}
                title="Delete past chat session"
                aria-label="Delete chat"
              >
                🗑️
              </button>
            </div>
          ))}
          {chats.length === 0 && (
            <div className="historyEmpty">No past chats</div>
          )}
        </div>

        <div className="sidebar-bottom">
          {currentUser.role === "admin" && (
            <button
              className="settingsBtn"
              onClick={() => {
                setSettingsSaveMsg("");
                setSettingsOpen(true);
              }}
            >
              ⚙️ Admin LLM & System Settings
            </button>
          )}
          <button className="logoutBtn" onClick={handleLogout}>
            🚪 Sign Out
          </button>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="main">
        {settingsOpen && currentUser.role === "admin" ? (
          <div className="settings">
            <div className="card" style={{ maxWidth: "860px" }}>
              <div className="settingsHead">
                <div>
                  <h1>Admin Azure OpenAI Settings</h1>
                  <p>Configure Azure OpenAI. Keys stay on the backend and are masked when displayed.</p>
                </div>
                <button onClick={() => setSettingsOpen(false)}>Close</button>
              </div>

              <label>
                <code>AZURE_OPENAI_ENDPOINT</code>
              </label>
              <input
                type="text"
                value={settings.azureOpenaiEndpoint}
                onChange={(e) => setSettings({ ...settings, azureOpenaiEndpoint: e.target.value })}
                placeholder="https://your-resource-name.openai.azure.com/"
              />

              <label>
                <code>AZURE_OPENAI_KEY</code> (Saved directly to <code>.env</code>)
              </label>
              <input
                type="password"
                value={settings.azureOpenaiKey}
                onChange={(e) => setSettings({ ...settings, azureOpenaiKey: e.target.value })}
                placeholder={
                  settings.azureOpenaiMaskedKey
                    ? `Current .env key: ${settings.azureOpenaiMaskedKey} — Enter new key to replace, or leave blank to keep current`
                    : "Paste your AZURE_OPENAI_KEY here"
                }
              />

              <label>
                <code>AZURE_OPENAI_DEPLOYMENT_NAME</code> (Chat / LLM Deployment Name)
              </label>
              <input
                type="text"
                value={settings.azureOpenaiDeploymentName}
                onChange={(e) => setSettings({ ...settings, azureOpenaiDeploymentName: e.target.value })}
                placeholder="e.g. gpt-4o, gpt-4o-mini, gpt-4"
              />

              <label>
                <code>AZURE_OPENAI_EMBEDDING_DEPLOYMENT</code> (Azure Text-Embedding-3 Deployment Name)
              </label>
              <input
                type="text"
                value={settings.azureOpenaiEmbeddingDeployment}
                onChange={(e) => setSettings({ ...settings, azureOpenaiEmbeddingDeployment: e.target.value })}
                placeholder="e.g. text-embedding-3-small or text-embedding-3-large"
              />

              <label>
                <code>AZURE_OPENAI_API_VERSION</code>
              </label>
              <input
                type="text"
                value={settings.azureOpenaiApiVersion}
                onChange={(e) => setSettings({ ...settings, azureOpenaiApiVersion: e.target.value })}
                placeholder="e.g. 2024-02-01"
              />

              <button className="save" onClick={() => saveSettings()}>
                Save Azure Configuration &amp; Apply
              </button>

              {settingsSaveMsg && (
                <div
                  style={{
                    marginTop: "12px",
                    padding: "10px 14px",
                    borderRadius: "8px",
                    background: "#dcfce7",
                    border: "1px solid #86efac",
                    color: "#166534",
                    fontSize: "13px",
                    fontWeight: 600,
                  }}
                >
                  {settingsSaveMsg}
                </div>
              )}

              {/* ADMIN-ONLY KENVUE TEMPLATE GUIDELINES STATUS */}
              <div className="admin-template-section">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                  <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
                    <span>🔒</span> Official Kenvue Master SOP-WI Template Standard
                  </h3>
                  <span style={{
                    background: "#dcfce7",
                    color: "#166534",
                    padding: "3px 10px",
                    borderRadius: "12px",
                    fontSize: "12px",
                    fontWeight: 700,
                    border: "1px solid #86efac"
                  }}>
                    ● Active &amp; Locked
                  </span>
                </div>
                <p style={{ color: "#475569", fontSize: "13px", lineHeight: "1.5", margin: "6px 0 12px 0" }}>
                  The official 7-page Kenvue Master SOP-WI Template (Standard <strong>SOP-STD-001</strong>) is permanently hardcoded and enforced as the immutable system standard. Manual template uploads have been retired to eliminate standard divergence and maintain rigorous GMP/QMS audit compliance across all uploads.
                </p>

                <div className="template-status-badge" style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "12px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
                    <div><strong>Standard Name:</strong> Kenvue Master SOP-WI Template_en-EN</div>
                    <div><strong>Standard ID:</strong> SOP-STD-001 (Rev 1.0)</div>
                    <div><strong>Mandatory Sections:</strong> 1.0, 2.0, 3.0, 4.0, 7.0</div>
                    <div><strong>Required Tables:</strong> Key Terms, Roles, References, Revision History</div>
                    <div><strong>Writing Rule:</strong> Imperative Active Voice ("must", "must not")</div>
                    <div><strong>Prohibited Words:</strong> "should", "shall", "will" (Zero Tolerance)</div>
                  </div>
                </div>

                <div style={{
                  marginTop: "12px",
                  padding: "10px 14px",
                  background: "#eff6ff",
                  borderRadius: "8px",
                  border: "1px solid #bfdbfe",
                  fontSize: "12px",
                  color: "#1e40af",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px"
                }}>
                  <span>ℹ️</span>
                  <span>
                    All SOP uploads, scoring evaluations, AI optimization, harmonization, and simplification agents are strictly bound to this central specification.
                  </span>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Header */}
            <header className="top">
              <div className="top-left">
                <span className="top-title">{active?.title || "Kenvue SOP Assistant"}</span>
                {activeSop?.has_sop && (
                  <>
                    {activeSop.documents?.length > 1 ? (
                      <div className="top-sop-navigator">
                        <button
                          type="button"
                          className={`top-sop-tab-pill ${selectedDocId === "all" ? "active" : ""}`}
                          onClick={() => {
                            setSelectedDocId("all");
                            setOptResult(null);
                            setShowOptForm(false);
                          }}
                          title="View All Uploaded SOPs Overview"
                        >
                          📚 Overview ({activeSop.documents.length})
                        </button>
                        {activeSop.documents.map((d, i) => {
                          const isAct = selectedDocId === d.id;
                          const dScore = d.optimized_scores?.average_score || d.scores?.average_score || 0;
                          const lMeta = getLangMeta(d.detected_language || d.original_language || "English");
                          return (
                            <button
                              key={d.id}
                              type="button"
                              className={`top-sop-tab-pill ${isAct ? "active" : ""}`}
                              onClick={() => selectIndividualSop(d)}
                              title={`SOP #${i + 1}: ${d.filename} (${dScore}%)`}
                            >
                              <span>{lMeta.flag}</span>
                              <span className="pill-name">SOP #{i + 1}</span>
                              <span className="pill-score">{dScore}%</span>
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="sop-badge">
                        📄 {activeSop.document?.filename} · {getLangMeta(activeSop.document?.detected_language).flag}{" "}
                        {activeSop.document?.detected_language || "English"}
                      </span>
                    )}
                    {artifacts.length > 0 && (
                      <button className="sop-artifacts-btn" onClick={() => setArtifactsModalOpen(true)}>
                        🖼️ Media ({artifacts.length})
                      </button>
                    )}
                    <button className="end-chat-btn" onClick={handleEndChat} title="End chat & archive summary">
                      🏁 End Chat
                    </button>
                  </>
                )}
              </div>
              <div className="top-right" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "4px 10px",
                    borderRadius: "999px",
                    background: activeLlmUnavailableError ? "#fef2f2" : "#f0fdf4",
                    border: activeLlmUnavailableError ? "1px solid #fecaca" : "1px solid #bbf7d0",
                    color: activeLlmUnavailableError ? "#991b1b" : "#166534",
                    fontSize: "12px",
                    fontWeight: 600,
                  }}
                  title={activeLlmUnavailableError ? "LLM Service Unavailable" : "Selected LLM provider configured by Admin"}
                >
                  {activeLlmUnavailableError
                    ? `🔴 AZURE OPENAI · LLM UNAVAILABLE`
                    : `🟢 AZURE OPENAI · ${settings.model}`}
                </span>
              </div>
            </header>

            {/* Chat Body */}
            <section className="chat">
              {!active ? (
                <div className="welcome-container">
                  <div className="welcome-header">
                    <h1>SOP Optimization Workspace</h1>
                    <p>Start a new conversation to audit, score, and optimize your Standard Operating Procedures across multiple languages.</p>
                  </div>
                  <button className="file-input-label" onClick={newChat}>
                    + Create New Chat
                  </button>
                </div>
              ) : (
                <>
                  <div className="messages">
                    {/* SOP UPLOAD BOX (When no SOP uploaded yet) */}
                    {!activeSop && (
                      <div className={`welcome-container ${uploading ? "has-uploading" : ""}`}>
                        <div className="welcome-header">
                          <h1>Upload Multilingual Procedure Documents</h1>
                          <p>
                            Upload up to 10 SOP documents (PDF or DOCX) in any supported language (English, Japanese, Chinese, German, French, Spanish, Korean, etc.). Non-English SOPs are automatically translated to canonical English via NLLB-200 for unified semantic comparison and cross-language type discovery while preserving original documents.
                          </p>
                        </div>

                        <div
                          className={`sop-card ${uploading ? "is-uploading" : ""} ${dragOver ? "drag-over" : ""}`}
                          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                          onDragLeave={() => setDragOver(false)}
                          onDrop={(e) => {
                            e.preventDefault();
                            setDragOver(false);
                            if (e.dataTransfer.files?.length) handleFileUpload(e.dataTransfer.files);
                          }}
                        >
                          {uploading ? (
                            <PipelineProgressBar
                              mode="upload"
                              progress={uploadProgress}
                              currentStageIndex={uploadStageIndex}
                              stageDetail={uploadStageDetail}
                              title="Detecting Languages, Translating via NLLB-200 & Indexing SOPs"
                              badgeText="KENVUE MULTILINGUAL NLLB + SEMANTIC DISCOVERY PIPELINE"
                            />
                          ) : (
                            <>
                              <div className="sop-icon">📚</div>
                              <h2>Drop up to 10 Multilingual SOP Documents (PDF or DOCX) here</h2>
                              <p>Automatic source language detection · NLLB-200 canonical English processing · Native target language output</p>

                              <LlmErrorBanner
                                message={uploadError || (settings.loaded && !settings.configured ? activeLlmUnavailableError : "")}
                                onDismiss={clearAllLlmErrors}
                                onOpenSettings={() => setSettingsOpen(true)}
                                isAdmin={currentUser?.role === "admin"}
                              />

                              <div className="upload-actions">
                                <label className="file-input-label">
                                  <span>Choose SOP Documents (up to 10)</span>
                                  <input
                                    ref={fileInputRef}
                                    type="file"
                                    multiple
                                    accept=".pdf,.docx"
                                    className="file-input-hidden"
                                    onChange={(e) => {
                                      if (e.target.files?.length) handleFileUpload(e.target.files);
                                    }}
                                  />
                                </label>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Multi-SOP Navigator Panel */}
                    {activeSop?.documents?.length > 1 && (
                      <div className="multi-sop-nav-panel">
                        <div className="multi-sop-nav-header">
                          <div className="multi-sop-nav-title-wrap">
                            <span className="multi-sop-nav-title">
                              🗂️ Uploaded SOP Navigator ({activeSop.documents.length} Documents)
                            </span>
                            <span className="multi-sop-nav-subtitle">
                              Click <strong>All Uploaded SOPs</strong> to compare &amp; harmonize, or click any <strong>SOP Card</strong> below to inspect &amp; optimize it individually.
                            </span>
                          </div>
                          <div className="multi-sop-nav-right">
                            {selectedDocId !== "all" && (
                              <div className="multi-sop-stepper-bar">
                                <button
                                  type="button"
                                  className="multi-sop-back-btn"
                                  onClick={() => {
                                    setSelectedDocId("all");
                                    setOptResult(null);
                                    setShowOptForm(false);
                                  }}
                                >
                                  ← All SOPs Overview
                                </button>
                                <button
                                  type="button"
                                  className="multi-sop-step-btn"
                                  disabled={currentDocIndex <= 0}
                                  onClick={() => {
                                    if (currentDocIndex > 0) {
                                      selectIndividualSop(activeSop.documents[currentDocIndex - 1]);
                                    }
                                  }}
                                  title="Previous SOP"
                                >
                                  ◀ Prev SOP
                                </button>
                                <span className="multi-sop-step-counter">
                                  SOP {currentDocIndex + 1} of {activeSop.documents.length}
                                </span>
                                <button
                                  type="button"
                                  className="multi-sop-step-btn"
                                  disabled={currentDocIndex < 0 || currentDocIndex >= activeSop.documents.length - 1}
                                  onClick={() => {
                                    if (currentDocIndex >= 0 && currentDocIndex < activeSop.documents.length - 1) {
                                      selectIndividualSop(activeSop.documents[currentDocIndex + 1]);
                                    }
                                  }}
                                  title="Next SOP"
                                >
                                  Next SOP ▶
                                </button>
                              </div>
                            )}
                            <div
                              className="sop-cluster-badge"
                              title="Normalized to Canonical English via NLLB-200 & Semantic Type Discovery"
                            >
                              <span>🌐 NLLB Canonical English · Semantic Analysis ({activeSop.documents.length})</span>
                            </div>
                          </div>
                        </div>

                        <div className="doc-tabs-bar">
                          <button
                            type="button"
                            className={`doc-tab-btn overview-card ${selectedDocId === "all" ? "active" : ""}`}
                            onClick={() => {
                              setSelectedDocId("all");
                              setOptResult(null);
                              setShowOptForm(false);
                            }}
                          >
                            <div className="doc-tab-top-row">
                              <span className="doc-tab-index-badge overview">📚 COLLECTION</span>
                              <span className="doc-tab-score">
                                Avg: {activeSop.collection_scores?.average_score || activeSop.document?.scores?.average_score || 0}%
                              </span>
                            </div>
                            <div className="doc-tab-filename-row">
                              <span className="doc-tab-big-icon">🗂️</span>
                              <span className="doc-tab-filename">All Uploaded SOPs ({activeSop.documents.length})</span>
                            </div>
                            <div className="doc-tab-bottom-row">
                              <span className="doc-tab-lang-pill">
                                🌐 Cross-SOP Harmonization
                              </span>
                              <span className="doc-tab-cta">
                                {selectedDocId === "all" ? "● Viewing Overview" : "Open Overview →"}
                              </span>
                            </div>
                          </button>

                          {activeSop.documents.map((doc, idx) => {
                            const docScore = doc.optimized_scores?.average_score || doc.scores?.average_score || 0;
                            const isDocActive = selectedDocId === doc.id;
                            const langMeta = getLangMeta(doc.detected_language || doc.original_language || "English");
                            const isOptimized = Boolean(doc.has_optimized_sop || doc.optimized_scores);
                            return (
                              <button
                                key={doc.id || idx}
                                type="button"
                                className={`doc-tab-btn ${isDocActive ? "active" : ""}`}
                                onClick={() => selectIndividualSop(doc)}
                                title={`${doc.filename} · Detected Language: ${langMeta.language} · Compliance Score: ${docScore}%`}
                              >
                                <div className="doc-tab-top-row">
                                  <span className="doc-tab-index-badge">
                                    SOP #{idx + 1} {isOptimized ? "✨" : ""}
                                  </span>
                                  <span className="doc-tab-lang-pill">
                                    {langMeta.flag} {langMeta.language}
                                  </span>
                                  <span className="doc-tab-score">{docScore}%</span>
                                </div>
                                <div className="doc-tab-filename-row">
                                  <span className="doc-tab-big-icon">📄</span>
                                  <span className="doc-tab-filename">
                                    {doc.filename.length > 36 ? doc.filename.slice(0, 34) + "..." : doc.filename}
                                  </span>
                                </div>
                                <div className="doc-tab-bottom-row">
                                  <span className="doc-tab-status-text">
                                    {isOptimized ? "✨ Optimized" : "📊 Individual Audit"}
                                  </span>
                                  <span className="doc-tab-cta">
                                    {isDocActive ? "● Viewing SOP" : "Inspect & Optimize →"}
                                  </span>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* MULTI-SOP HARMONIZATION PROGRESS BAR                     */}
                    {/* ======================================================== */}
                    {harmonizing && (
                      <PipelineProgressBar
                        mode="harmonize"
                        progress={harmProgress}
                        currentStageIndex={harmStageIndex}
                        stageDetail={harmStageDetail}
                        title={`Harmonizing Selected SOPs & Generating ${selectedHarmonizeLanguage} Output`}
                        badgeText="KENVUE MULTILINGUAL HARMONIZATION PIPELINE"
                        customSteps={HARMONIZE_PIPELINE_STEPS}
                      />
                    )}

                    {/* ======================================================== */}
                    {/* 1. MULTI-SOP SIMILARITY & DUPLICATE DETECTION            */}
                    {/* ======================================================== */}
                    {isCollectionOverview && similarityData && !harmonizing && (
                      <div className="similarity-card">
                        <div className="similarity-header">
                          <div className="similarity-title">
                            <span>🌐 Multi-SOP Semantic & Procedural Similarity (Azure text-embedding-3)</span>
                          </div>
                          <div className="sop-cluster-badge" style={{ fontSize: "12px", padding: "4px 12px" }}>
                            <span>NLLB-200 Normalized · Exact Cosine Matrix</span>
                          </div>
                        </div>

                        {similarityData.executive_summary && (
                          <div className="similarity-exec-summary">
                            <strong>Executive Summary:</strong> {similarityData.executive_summary}
                          </div>
                        )}

                        {/* Pairwise Similarity Matrix Table */}
                        {similarityData.symmetric_matrix && similarityData.symmetric_matrix.filenames?.length > 1 && (
                          <div className="pairwise-matrix-section">
                            <div className="pairwise-matrix-header">
                              <span className="pairwise-matrix-title">📊 Pairwise Semantic Similarity Matrix</span>
                              <span className="pairwise-matrix-subtitle">
                                Exact cross-document cosine similarity scores between all uploaded SOPs
                              </span>
                            </div>
                            <div className="pairwise-table-wrapper">
                              <table className="pairwise-matrix-table">
                                <thead>
                                  <tr>
                                    <th className="matrix-corner">SOP Document</th>
                                    {similarityData.symmetric_matrix.filenames.map((fname, fIdx) => (
                                      <th key={fIdx} title={fname}>
                                        #{fIdx + 1}: {fname.length > 18 ? fname.slice(0, 16) + "..." : fname}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {similarityData.symmetric_matrix.filenames.map((rowName, rIdx) => (
                                    <tr key={rIdx}>
                                      <td className="matrix-row-header" title={rowName}>
                                        <strong>#{rIdx + 1}</strong> {rowName.length > 22 ? rowName.slice(0, 20) + "..." : rowName}
                                      </td>
                                      {similarityData.symmetric_matrix.matrix[rIdx]?.map((val, cIdx) => {
                                        const isSelf = rIdx === cIdx;
                                        const status =
                                          similarityData.symmetric_matrix.status_matrix?.[rIdx]?.[cIdx] ||
                                          (val >= 70 ? "Highly Similar" : val >= 45 ? "Moderately Similar" : "Distinct SOP");
                                        const cellClass = isSelf
                                          ? "cell-self"
                                          : val >= 70
                                          ? "cell-high"
                                          : val >= 45
                                          ? "cell-mod"
                                          : "cell-diff";
                                        return (
                                          <td
                                            key={cIdx}
                                            className={`matrix-cell ${cellClass}`}
                                            title={`${rowName} vs ${similarityData.symmetric_matrix.filenames[cIdx]}: ${val}% similarity (${isSelf ? "Self" : val < 45 ? "Distinct / Unrelated procedure" : status})`}
                                          >
                                            <span className="cell-value">{isSelf ? "100%" : `${val}%`}</span>
                                            <span className="cell-status">{isSelf ? "Self" : (val < 45 ? "Distinct SOP" : status)}</span>
                                          </td>
                                        );
                                      })}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        {similarityData.similarity_groups?.length > 0 && (
                          <div className="similarity-groups-grid">
                            {similarityData.similarity_groups.map((grp) => {
                              const isHighlySimilar = grp.status === "Highly Similar";
                              const isMod = grp.status === "Moderately Similar";
                              const isStandalone =
                                grp.is_standalone ||
                                grp.status === "Standalone SOP" ||
                                grp.document_count === 1 ||
                                grp.document_ids?.length === 1 ||
                                grp.document_names?.length === 1;

                              const badgeClass = isHighlySimilar
                                ? "highly-similar"
                                : isMod
                                ? "moderately-similar"
                                : isStandalone
                                ? "standalone"
                                : "different";
                              const cardClass = isHighlySimilar ? "is-similar" : "is-different";

                              return (
                                <div key={grp.group_id} className={`similarity-group-item ${cardClass}`}>
                                  <div className="group-top-row">
                                    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                                      <span className="group-name">{grp.group_name}</span>
                                      {grp.discovered_type && (
                                        <span className="group-domain-pill">
                                          🏷️ {grp.discovered_type} {grp.category ? `· ${grp.category}` : ""}
                                        </span>
                                      )}
                                    </div>
                                    <span className={`group-score-badge ${badgeClass}`}>
                                      {isStandalone
                                        ? "Standalone SOP • Distinct"
                                        : `${grp.similarity_pct}% · ${grp.status}`}
                                    </span>
                                  </div>

                                  <div className="group-status-desc">{grp.reason}</div>
                                  {grp.operational_scope && (
                                    <div className="group-scope-text">
                                      <strong>Scope:</strong> {grp.operational_scope}
                                    </div>
                                  )}

                                  <div className="group-docs-list">
                                    {grp.document_names.map((docName, dIdx) => {
                                      const matchedDoc = activeSop.documents?.find((d) => d.filename === docName);
                                      const lMeta = getLangMeta(matchedDoc?.detected_language || "English");
                                      return (
                                        <div key={dIdx} className="group-doc-pill">
                                          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                                            <span>📄 {docName}</span>
                                            <span className="inline-lang-chip">
                                              {lMeta.flag} Detected: {lMeta.language} · Internal: English
                                            </span>
                                          </div>
                                          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                                            {isHighlySimilar && (
                                              <span style={{ color: "#15803d", fontSize: "11px", fontWeight: 750 }}>
                                                Candidate for Harmonization
                                              </span>
                                            )}
                                            {matchedDoc && (
                                              <button
                                                type="button"
                                                className="quick-open-sop-btn"
                                                onClick={() => selectIndividualSop(matchedDoc)}
                                                title={`Open individual scorecard & optimization for ${docName}`}
                                              >
                                                🔍 Open SOP →
                                              </button>
                                            )}
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>

                                  {((similarityData.procedural_overlaps && similarityData.procedural_overlaps.length > 0) ||
                                    (similarityData.parameter_conflicts && similarityData.parameter_conflicts.length > 0)) && (
                                    <div>
                                      <button
                                        type="button"
                                        className="group-details-toggle"
                                        onClick={() => setShowOverlapDetails(!showOverlapDetails)}
                                      >
                                        {showOverlapDetails ? "▲ Hide Overlaps & Parameter Conflicts" : "▼ View Overlaps & Parameter Conflicts"}
                                      </button>

                                      {showOverlapDetails && (
                                        <div className="group-extra-details">
                                          {similarityData.procedural_overlaps?.length > 0 && (
                                            <div style={{ marginBottom: "8px" }}>
                                              <strong style={{ color: "#1e293b", display: "block", marginBottom: "4px" }}>
                                                Procedural Overlaps:
                                              </strong>
                                              {similarityData.procedural_overlaps.map((po, pIdx) => (
                                                <span key={pIdx} className="overlap-item" title={po.description}>
                                                  ⚙️ {po.procedure} ({po.shared_documents.length} SOPs)
                                                </span>
                                              ))}
                                            </div>
                                          )}

                                          {similarityData.parameter_conflicts?.length > 0 && (
                                            <div>
                                              <strong style={{ color: "#1e293b", display: "block", marginBottom: "4px" }}>
                                                Parameter Discrepancies (Reconciled to GMP limit):
                                              </strong>
                                              {similarityData.parameter_conflicts.map((pc, cIdx) => (
                                                <span key={cIdx} className="conflict-pill" title={pc.action}>
                                                  ⚠️ {pc.parameter}: {pc.values.map((v) => `${v.doc}: ${v.value}`).join(" vs ")} ➔ Target: {pc.resolved_gmp_limit}
                                                </span>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}

                        {/* ======================================================== */}
                        {/* 2. HARMONIZE SELECTOR & OUTPUT LANGUAGE SELECTION        */}
                        {/* ======================================================== */}
                        <div className="harmonize-selector-box">
                          <div className="harmonize-prompt-title">
                            <span>✨ Harmonize Similar SOPs into a Single Standardized Kenvue SOP</span>
                          </div>
                          <div className="harmonize-prompt-sub">
                            Select which procedures to unify. All selected SOPs are compared and harmonized using their canonical English representations, then generated in your chosen output language below.
                          </div>

                          <div className="harmonize-checklist">
                            {activeSop.documents.map((doc, docIdx) => {
                              const isChecked = selectedHarmonizeIds.includes(doc.id);
                              const lMeta = getLangMeta(doc.detected_language || doc.original_language || "English");
                              return (
                                <div
                                  key={doc.id}
                                  className={`harmonize-check-card ${isChecked ? "checked" : ""}`}
                                  onClick={() => {
                                    setSelectedHarmonizeIds((prev) =>
                                      prev.includes(doc.id) ? prev.filter((id) => id !== doc.id) : [...prev, doc.id]
                                    );
                                  }}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => {}}
                                  />
                                  <div className="harmonize-doc-info">
                                    <span className="harmonize-doc-title" title={doc.filename}>
                                      SOP #{docIdx + 1}: {doc.filename.length > 32 ? doc.filename.slice(0, 30) + "..." : doc.filename}
                                    </span>
                                    <span className="harmonize-doc-lang">
                                      {lMeta.flag} Detected Language: <strong>{lMeta.language}</strong> · Internal Processing: <strong>English</strong>
                                    </span>
                                    <span className="harmonize-doc-sub">
                                      Initial Compliance: <strong>{doc.scores?.average_score || 0}%</strong> ·{" "}
                                      {doc.translation_status === "completed"
                                        ? "NLLB Translated to English"
                                        : "Canonical English"}
                                    </span>
                                    <div style={{ marginTop: "6px" }}>
                                      <button
                                        type="button"
                                        className="quick-open-sop-btn"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          selectIndividualSop(doc);
                                        }}
                                        title={`Inspect or optimize ${doc.filename} individually`}
                                      >
                                        🔍 Inspect / Optimize SOP #{docIdx + 1} →
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>

                          {/* ======================================================== */}
                          {/* DEDICATED LANGUAGE SELECTION STEP FOR HARMONIZATION      */}
                          {/* ======================================================== */}
                          <div className="harmonize-language-step-card">
                            <div className="harmonize-lang-step-header">
                              <span className="harmonize-lang-step-badge">🌐 OUTPUT LANGUAGE SELECTION</span>
                              <span className="harmonize-lang-internal-note">
                                Internal Processing Language: <strong>English (NLLB-200 Canonical)</strong>
                              </span>
                            </div>

                            <div className="harmonize-detected-languages-summary">
                              <span className="detected-summary-label">
                                The uploaded SOPs contain the following languages:
                              </span>
                              <div className="detected-summary-pills">
                                {uniqueUploadedLanguages.map((langObj) => (
                                  <span key={langObj.language} className="detected-lang-summary-pill">
                                    {langObj.flag} {langObj.language}
                                  </span>
                                ))}
                              </div>
                            </div>

                            <div className="harmonize-lang-question">
                              In which language would you like the harmonized SOP to be generated?
                            </div>

                            <div className="harmonize-lang-checkbox-grid">
                              {uniqueUploadedLanguages.map((langObj) => {
                                const isSelected = selectedHarmonizeLanguage === langObj.language;
                                return (
                                  <div
                                    key={langObj.language}
                                    className={`harmonize-lang-checkbox-option ${isSelected ? "selected" : ""}`}
                                    onClick={() => setSelectedHarmonizeLanguage(langObj.language)}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isSelected}
                                      onChange={() => setSelectedHarmonizeLanguage(langObj.language)}
                                      aria-label={`Select ${langObj.language} as output language`}
                                    />
                                    <div className="harmonize-lang-option-info">
                                      <div className="harmonize-lang-option-top">
                                        <span className="harmonize-lang-flag">{langObj.flag}</span>
                                        <span className="harmonize-lang-name">{langObj.language}</span>
                                      </div>
                                      <span className="harmonize-lang-meta">
                                        {langObj.native_name} · {langObj.nllb_code} ({langObj.document_count} uploaded SOP{langObj.document_count > 1 ? "s" : ""})
                                      </span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>

                          <LlmErrorBanner
                            message={harmonizeError}
                            onDismiss={() => setHarmonizeError("")}
                            onOpenSettings={() => setSettingsOpen(true)}
                            isAdmin={currentUser?.role === "admin"}
                          />

                          <div className="harmonize-actions-row">
                            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                              <button
                                type="button"
                                className="select-all-btn"
                                onClick={() => {
                                  if (selectedHarmonizeIds.length === activeSop.documents.length) {
                                    setSelectedHarmonizeIds([]);
                                  } else {
                                    setSelectedHarmonizeIds(activeSop.documents.map((d) => d.id));
                                  }
                                }}
                              >
                                {selectedHarmonizeIds.length === activeSop.documents.length ? "Deselect All" : "Select All SOPs"}
                              </button>

                              {similarityData.similarity_groups?.find((g) => g.status === "Highly Similar") && (
                                <button
                                  type="button"
                                  className="select-all-btn"
                                  style={{ background: "#dcfce7", color: "#15803d", borderColor: "#86efac" }}
                                  onClick={() => {
                                    const simGroup = similarityData.similarity_groups.find((g) => g.status === "Highly Similar");
                                    if (simGroup?.document_ids) {
                                      setSelectedHarmonizeIds(simGroup.document_ids);
                                    }
                                  }}
                                >
                                  🎯 Select Highly Similar Group ({similarityData.similarity_groups.find((g) => g.status === "Highly Similar")?.document_names.length} SOPs)
                                </button>
                              )}
                            </div>

                            <button
                              type="button"
                              className="harmonize-btn"
                              disabled={selectedHarmonizeIds.length < 2 || harmonizing || !selectedHarmonizeLanguage}
                              onClick={handleHarmonize}
                            >
                              <span>
                                🔗 Harmonize Selected SOPs in {selectedHarmonizeLanguage} ({selectedHarmonizeIds.length} SOPs)
                              </span>
                            </button>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* 3. HARMONIZED SOP WORKSPACE (VERSION HISTORY & METRICS)   */}
                    {/* ======================================================== */}
                    {isCollectionOverview && harmonizedVersions.length > 0 && activeHarmonizedVersion && !harmonizing && (
                      <div className="harmonized-workspace-card">
                        <div className="harmonized-workspace-head">
                          <div className="harmonized-badge-title">
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                              <div className="harmonized-badge-tag">
                                <span>✨ Standardized Harmonized SOP (v{activeHarmonizedVersion.version_number})</span>
                              </div>
                              <span className="sop-lang-indicator-pill">
                                {getLangMeta(activeHarmonizedVersion.output_language || "English").flag} Output Language:{" "}
                                <strong>{activeHarmonizedVersion.output_language || "English"}</strong>
                              </span>
                              <span className="sop-lang-indicator-pill internal">
                                🇺🇸 Internal Processing: <strong>English</strong>
                              </span>
                            </div>
                            <div className="harmonized-doc-title">{activeHarmonizedVersion.title}</div>
                          </div>

                          <div className={`scorecard-avg-badge ${getScoreBadgeClass(activeHarmonizedVersion.overall_score || activeHarmonizedVersion.scores?.average_score || 90)}`}>
                            <span>Overall SOP Score:</span>
                            <span style={{ fontSize: "20px" }}>
                              {activeHarmonizedVersion.overall_score || activeHarmonizedVersion.scores?.average_score || 90}%
                            </span>
                          </div>
                        </div>

                        {/* Version History Timeline Bar (Strict Immutability) */}
                        <div className="version-timeline-bar">
                          <span className="timeline-label">Version History:</span>
                          {harmonizedVersions.map((v) => {
                            const isVerActive = selectedVersionId === v.id;
                            const verTypeLabel =
                              v.action_type === "harmonize"
                                ? "Initial Harmonized"
                                : v.action_type === "simplify"
                                ? "Simplified"
                                : "Refined";
                            const vLangMeta = getLangMeta(v.output_language || "English");
                            return (
                              <button
                                key={v.id}
                                type="button"
                                className={`version-chip ${isVerActive ? "active" : ""}`}
                                onClick={() => {
                                  setSelectedVersionId(v.id);
                                  setShowSimplifyPanel(false);
                                }}
                                title={`${v.title} (${v.output_language || "English"}) - ${v.change_summary}`}
                              >
                                <span>
                                  📄 v{v.version_number} · {verTypeLabel} ({vLangMeta.flag} {v.output_language || "English"})
                                </span>
                                <span className="version-chip-score">
                                  {v.overall_score || v.scores?.average_score || 0}%
                                </span>
                              </button>
                            );
                          })}
                        </div>

                        {/* Lineage & Provenance Box */}
                        <div className="lineage-provenance-box">
                          <div className="lineage-row">
                            <span className="lineage-label">Source SOPs:</span>
                            <span>{activeHarmonizedVersion.source_filenames?.join(", ") || "Uploaded Documents"}</span>
                          </div>
                          <div className="lineage-row">
                            <span className="lineage-label">Source Languages:</span>
                            <span>
                              {(activeHarmonizedVersion.detected_languages?.length
                                ? activeHarmonizedVersion.detected_languages
                                : uniqueUploadedLanguages.map((l) => l.language)
                              ).join(", ")}{" "}
                              ➔ <strong>Canonical English (Internal)</strong> ➔{" "}
                              <strong>{activeHarmonizedVersion.output_language || "English"} (Output)</strong>
                            </span>
                          </div>
                          <div className="lineage-row">
                            <span className="lineage-label">Lineage:</span>
                            <span>
                              {activeHarmonizedVersion.parent_version_id
                                ? `Derived from parent version (ID: ${activeHarmonizedVersion.parent_version_id.slice(0, 8)}...)`
                                : "Root Consolidated Document (Consolidated from canonical English procedures)"}
                            </span>
                          </div>
                          <div className="lineage-row">
                            <span className="lineage-label">Modifications:</span>
                            <span>{activeHarmonizedVersion.change_summary || "Harmonized into Kenvue 10-tier procedure."}</span>
                          </div>
                        </div>

                        {/* 6-Dimension Quality Scorecard */}
                        <div className="scorecard-meters-6">
                          <div className="meter-card-small">
                            <div className="meter-label">
                              <span>📋 Template Match</span>
                              <span style={{ color: "#16a34a" }}>{activeHarmonizedVersion.template_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{ width: `${activeHarmonizedVersion.template_score}%`, background: "#16a34a" }}
                              />
                            </div>
                          </div>

                          <div className="meter-card-small">
                            <div className="meter-label">
                              <span>📖 Readability</span>
                              <span style={{ color: "#2563eb" }}>{activeHarmonizedVersion.readability_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{ width: `${activeHarmonizedVersion.readability_score}%`, background: "#2563eb" }}
                              />
                            </div>
                          </div>

                          <div className="meter-card-small">
                            <div className="meter-label">
                              <span>🛡️ Quality Precision</span>
                              <span style={{ color: "#16a34a" }}>{activeHarmonizedVersion.quality_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{ width: `${activeHarmonizedVersion.quality_score}%`, background: "#16a34a" }}
                              />
                            </div>
                          </div>

                          <div className="meter-card-small">
                            <div className="meter-label">
                              <span>🏛️ Kenvue Alignment</span>
                              <span style={{ color: "#059669" }}>{activeHarmonizedVersion.kenvue_alignment_score || 95}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{ width: `${activeHarmonizedVersion.kenvue_alignment_score || 95}%`, background: "#059669" }}
                              />
                            </div>
                          </div>

                          <div className="meter-card-small">
                            <div className="meter-label">
                              <span>✅ Completeness</span>
                              <span style={{ color: "#0d9488" }}>{activeHarmonizedVersion.completeness_score || 94}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{ width: `${activeHarmonizedVersion.completeness_score || 94}%`, background: "#0d9488" }}
                              />
                            </div>
                          </div>

                          <div className="meter-card-small" style={{ background: "#f0fdf4", borderColor: "#86efac" }}>
                            <div className="meter-label">
                              <span style={{ color: "#166534" }}>⭐ Overall Score</span>
                              <span style={{ color: "#166534", fontWeight: 800 }}>
                                {activeHarmonizedVersion.overall_score || activeHarmonizedVersion.scores?.average_score}%
                              </span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{
                                  width: `${activeHarmonizedVersion.overall_score || activeHarmonizedVersion.scores?.average_score}%`,
                                  background: "#16a34a",
                                }}
                              />
                            </div>
                          </div>
                        </div>

                        {/* Harmonized Actions Toolbar */}
                        <div className="harmonized-actions-toolbar">
                          <button
                            type="button"
                            className="harmonized-tool-btn primary"
                            onClick={() => {
                              setPdfPreviewUrl(activeHarmonizedVersion.preview_url);
                              setPdfPreviewTitle(
                                `Harmonized SOP v${activeHarmonizedVersion.version_number} (${activeHarmonizedVersion.output_language || "English"}) Preview`
                              );
                              setPdfPreviewOpen(true);
                            }}
                          >
                            👁️ Preview Harmonized PDF (v{activeHarmonizedVersion.version_number} · {activeHarmonizedVersion.output_language || "English"})
                          </button>

                          <a
                            href={`${API}${activeHarmonizedVersion.download_url}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="harmonized-tool-btn"
                            style={{ textDecoration: "none" }}
                          >
                            ⬇️ Download Harmonized PDF ({activeHarmonizedVersion.output_language || "English"})
                          </a>

                          <button
                            type="button"
                            className="harmonized-tool-btn simplify"
                            onClick={() => setShowSimplifyPanel(!showSimplifyPanel)}
                          >
                            ⚡ {showSimplifyPanel ? "Hide Simplification Recommendations" : "Simplify SOP"}
                          </button>

                          <button
                            type="button"
                            className="end-chat-btn"
                            onClick={handleEndChat}
                            style={{ marginLeft: "auto" }}
                          >
                            🏁 End Chat & Archive
                          </button>
                        </div>

                        {/* 4. SIMPLIFICATION RECOMMENDATIONS PANEL */}
                        {showSimplifyPanel && (
                          <div className="simplification-panel">
                            <div className="simplification-panel-head">
                              <div className="simplification-panel-title">
                                <span>⚡ Simplification Recommendations</span>
                              </div>
                              <button
                                type="button"
                                className="select-all-btn"
                                onClick={() => {
                                  if (selectedSimpRecs.length === simplificationCatalog.length) {
                                    setSelectedSimpRecs([]);
                                  } else {
                                    setSelectedSimpRecs(simplificationCatalog.map((c) => c.id));
                                  }
                                }}
                              >
                                {selectedSimpRecs.length === simplificationCatalog.length ? "Deselect All" : "Select All"}
                              </button>
                            </div>

                            <p style={{ fontSize: "12.5px", color: "#92400e", margin: "0 0 14px 0" }}>
                              Applying recommendations simplifies the canonical English representation and generates a new, immutable version (v{activeHarmonizedVersion.version_number + 1}) in <strong>{activeHarmonizedVersion.output_language || selectedHarmonizeLanguage || "English"}</strong>.
                            </p>

                            <div className="simplification-items-list">
                              {simplificationCatalog.map((item) => {
                                const isChecked = selectedSimpRecs.includes(item.id);
                                return (
                                  <div
                                    key={item.id}
                                    className={`simplification-item-card ${isChecked ? "checked" : ""}`}
                                    onClick={() => {
                                      setSelectedSimpRecs((prev) =>
                                        prev.includes(item.id) ? prev.filter((id) => id !== item.id) : [...prev, item.id]
                                      );
                                    }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isChecked}
                                      onChange={() => {}}
                                    />
                                    <div className="simplification-item-body">
                                      <span className="simplification-item-title">{item.title}</span>
                                      <span className="simplification-item-desc">{item.description}</span>
                                      <span className="simplification-item-benefit">✨ {item.benefit}</span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>

                            <LlmErrorBanner
                              message={simplifyError}
                              onDismiss={() => setSimplifyError("")}
                              onOpenSettings={() => setSettingsOpen(true)}
                              isAdmin={currentUser?.role === "admin"}
                            />

                            <button
                              type="button"
                              className="generate-opt-btn"
                              style={{ background: "#d97706" }}
                              disabled={simplifying || selectedSimpRecs.length === 0}
                              onClick={handleSimplify}
                            >
                              {simplifying
                                ? `Applying Simplification & Compiling ${activeHarmonizedVersion.output_language || "English"} PDF...`
                                : `🚀 Apply Selected Simplifications in ${activeHarmonizedVersion.output_language || "English"} (Generates v${activeHarmonizedVersion.version_number + 1})`}
                            </button>
                          </div>
                        )}

                        {/* 5. INTERACTIVE SOP REFINEMENT CONVERSATIONAL WORKSPACE */}
                        <div className="refinement-box">
                          <div className="refinement-head">
                            <span>💬 Interactive SOP Refinement Workspace ({activeHarmonizedVersion.output_language || "English"})</span>
                          </div>
                          <div className="refinement-sub">
                            Refine specific sections, tone, or formatting interactively. Refinements are processed on the canonical English representation and output in <strong>{activeHarmonizedVersion.output_language || "English"}</strong>.
                          </div>

                          <div className="refinement-examples">
                            <button
                              type="button"
                              className="refinement-example-pill"
                              onClick={() => setRefinementPrompt("Make Section 3 easier to understand.")}
                            >
                              💡 "Make Section 3 easier to understand."
                            </button>
                            <button
                              type="button"
                              className="refinement-example-pill"
                              onClick={() => setRefinementPrompt("The wording is too simple. Make it slightly more professional.")}
                            >
                              💡 "The wording is too simple. Make it slightly more professional."
                            </button>
                            <button
                              type="button"
                              className="refinement-example-pill"
                              onClick={() => setRefinementPrompt("Add an explicit PPE safety verification step before centrifuge startup.")}
                            >
                              💡 "Add an explicit PPE safety verification step before centrifuge startup."
                            </button>
                            <button
                              type="button"
                              className="refinement-example-pill"
                              onClick={() => setRefinementPrompt("Ensure all speed tolerances specify ± 25 RPM.")}
                            >
                              💡 "Ensure all speed tolerances specify ± 25 RPM."
                            </button>
                          </div>

                          <LlmErrorBanner
                            message={refineError}
                            onDismiss={() => setRefineError("")}
                            onOpenSettings={() => setSettingsOpen(true)}
                            isAdmin={currentUser?.role === "admin"}
                          />

                          <form onSubmit={handleRefine} className="refinement-input-row">
                            <input
                              type="text"
                              className="refinement-input"
                              value={refinementPrompt}
                              onChange={(e) => setRefinementPrompt(e.target.value)}
                              placeholder="Type refinement instructions (e.g. 'Make Section 3 easier to understand')..."
                              disabled={refining}
                            />
                            <button
                              type="submit"
                              className="refinement-send-btn"
                              disabled={refining || !refinementPrompt.trim()}
                            >
                              {refining ? "Refining..." : `Apply to v${activeHarmonizedVersion.version_number + 1} (${activeHarmonizedVersion.output_language || "English"})`}
                            </button>
                          </form>
                        </div>
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* QUICK SWITCHER BAR FOR INDIVIDUAL SOP VIEW               */}
                    {/* ======================================================== */}
                    {!isCollectionOverview && activeSop?.documents?.length > 1 && (
                      <div className="sop-quick-switcher-bar">
                        <div className="sop-quick-switcher-left">
                          <button
                            type="button"
                            className="quick-switch-back-btn"
                            onClick={() => {
                              setSelectedDocId("all");
                              setOptResult(null);
                              setShowOptForm(false);
                            }}
                          >
                            ← All SOPs Overview
                          </button>
                          <div className="quick-switch-stepper">
                            <button
                              type="button"
                              className="quick-switch-step-btn"
                              disabled={currentDocIndex <= 0}
                              onClick={() => {
                                if (currentDocIndex > 0) {
                                  selectIndividualSop(activeSop.documents[currentDocIndex - 1]);
                                }
                              }}
                              title="Previous SOP"
                            >
                              ◀ Prev SOP
                            </button>
                            <span className="quick-switch-counter">
                              SOP {currentDocIndex + 1} of {activeSop.documents.length}
                            </span>
                            <button
                              type="button"
                              className="quick-switch-step-btn"
                              disabled={currentDocIndex < 0 || currentDocIndex >= activeSop.documents.length - 1}
                              onClick={() => {
                                if (currentDocIndex >= 0 && currentDocIndex < activeSop.documents.length - 1) {
                                  selectIndividualSop(activeSop.documents[currentDocIndex + 1]);
                                }
                              }}
                              title="Next SOP"
                            >
                              Next SOP ▶
                            </button>
                          </div>
                        </div>

                        <div className="sop-quick-switcher-pills">
                          {activeSop.documents.map((d, i) => {
                            const isAct = selectedDocId === d.id;
                            const dScore = d.optimized_scores?.average_score || d.scores?.average_score || 0;
                            const lMeta = getLangMeta(d.detected_language || d.original_language || "English");
                            return (
                              <button
                                key={d.id}
                                type="button"
                                className={`quick-switch-pill ${isAct ? "active" : ""}`}
                                onClick={() => selectIndividualSop(d)}
                              >
                                <span>{lMeta.flag}</span>
                                <span className="pill-title">SOP #{i + 1}: {d.filename.length > 22 ? d.filename.slice(0, 20) + "..." : d.filename}</span>
                                <span className="pill-badge">{dScore}%</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* INDIVIDUAL SOP EVALUATION SCORECARD                      */}
                    {/* ======================================================== */}
                    {!isCollectionOverview && activeSop && scores && !optResult && (
                      <div className="scorecard-card">
                        <div className="scorecard-header">
                          <div className="scorecard-title">
                            <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                              <span>
                                📊 Kenvue SOP Compliance Scorecard{currentDoc?.filename ? ` · ${currentDoc.filename}` : ""}
                              </span>
                              {activeSop.documents?.length > 1 && (
                                <select
                                  className="scorecard-sop-select"
                                  value={currentDoc?.id || ""}
                                  onChange={(e) => {
                                    if (e.target.value === "all") {
                                      setSelectedDocId("all");
                                      setOptResult(null);
                                      setShowOptForm(false);
                                    } else {
                                      const found = activeSop.documents.find(d => d.id === e.target.value);
                                      if (found) selectIndividualSop(found);
                                    }
                                  }}
                                  title="Jump to another uploaded SOP"
                                >
                                  {activeSop.documents.map((d, i) => (
                                    <option key={d.id} value={d.id}>
                                      SOP #{i + 1}: {d.filename} ({d.optimized_scores?.average_score || d.scores?.average_score || 0}%)
                                    </option>
                                  ))}
                                </select>
                              )}
                            </div>
                          </div>
                          <div className={`scorecard-avg-badge ${getScoreBadgeClass(scores.average_score)}`}>
                            <span>Average Rating:</span>
                            <span style={{ fontSize: "19px" }}>{scores.average_score}%</span>
                          </div>
                        </div>

                        {/* MULTILINGUAL SOP LANGUAGE & NLLB METADATA BAR */}
                        {currentDoc && (
                          <div className="sop-language-banner">
                            <div className="sop-lang-banner-grid">
                              <div className="sop-lang-meta-item">
                                <span className="sop-lang-meta-label">Original Document</span>
                                <span className="sop-lang-meta-val">📄 {currentDoc.filename}</span>
                              </div>
                              <div className="sop-lang-meta-item">
                                <span className="sop-lang-meta-label">Detected & Output Language</span>
                                <span className="sop-lang-meta-val highlight">
                                  {getLangMeta(currentDoc.detected_language).flag}{" "}
                                  {currentDoc.detected_language || "English"}{" "}
                                  <small>({currentDoc.nllb_language_code || "eng_Latn"})</small>
                                </span>
                              </div>
                              <div className="sop-lang-meta-item">
                                <span className="sop-lang-meta-label">Internal Processing</span>
                                <span className="sop-lang-meta-val">
                                  🇺🇸 English <small>(Canonical NLLB-200)</small>
                                </span>
                              </div>
                              <div className="sop-lang-meta-item">
                                <span className="sop-lang-meta-label">NLLB Translation Status</span>
                                <span className="sop-lang-meta-val status-ok">
                                  {currentDoc.translation_status === "completed"
                                    ? "✓ Translated to Canonical English"
                                    : currentDoc.translation_status === "skipped_already_english"
                                    ? "✓ Skipped (Already in English)"
                                    : `✓ ${currentDoc.translation_status || "Ready"}`}
                                </span>
                              </div>
                            </div>

                            {currentDoc.id && (
                              <div className="sop-lang-banner-controls">
                                <button
                                  type="button"
                                  className="view-original-sop-btn"
                                  onClick={() => {
                                    const isDocx = (currentDoc.filename || "").toLowerCase().endsWith(".docx");
                                    if (isDocx) {
                                      window.open(`${API}/conversations/${active.id}/sop/${currentDoc.id}/original-pdf?download=true`, "_blank");
                                    } else {
                                      setPdfPreviewUrl(`/conversations/${active.id}/sop/${currentDoc.id}/original-pdf`);
                                      setPdfPreviewTitle(
                                        `Preserved Original SOP: ${currentDoc.filename} (${currentDoc.original_language || currentDoc.detected_language || "Original"})`
                                      );
                                      setPdfPreviewOpen(true);
                                    }
                                  }}
                                >
                                  {(currentDoc.filename || "").toLowerCase().endsWith(".docx")
                                    ? `⬇️ Download Original DOCX (${currentDoc.original_language || currentDoc.detected_language || "Original"})`
                                    : `📄 View Original SOP (${currentDoc.original_language || currentDoc.detected_language || "Original"})`}
                                </button>
                              </div>
                            )}
                          </div>
                        )}

                        <div className="scorecard-meters">
                          <div className="meter-box">
                            <div className="meter-label">
                              <span>📋 Template Compliance</span>
                              <span className="meter-value">{scores.template_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{
                                  width: `${scores.template_score}%`,
                                  background: scores.template_score >= 80 ? "#16a34a" : scores.template_score >= 60 ? "#eab308" : "#dc2626",
                                }}
                              />
                            </div>
                          </div>

                          <div className="meter-box">
                            <div className="meter-label">
                              <span>📖 Readability & Clarity</span>
                              <span className="meter-value">{scores.readability_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{
                                  width: `${scores.readability_score}%`,
                                  background: scores.readability_score >= 80 ? "#16a34a" : scores.readability_score >= 60 ? "#eab308" : "#dc2626",
                                }}
                              />
                            </div>
                          </div>

                          <div className="meter-box">
                            <div className="meter-label">
                              <span>🛡️ Quality & Safety Precision</span>
                              <span className="meter-value">{scores.quality_score}%</span>
                            </div>
                            <div className="meter-bar-bg">
                              <div
                                className="meter-bar-fill"
                                style={{
                                  width: `${scores.quality_score}%`,
                                  background: scores.quality_score >= 80 ? "#16a34a" : scores.quality_score >= 60 ? "#eab308" : "#dc2626",
                                }}
                              />
                            </div>
                          </div>
                        </div>

                        {scores.summary && <div className="scorecard-summary">{scores.summary}</div>}

                        {!showOptForm && (
                          <div className="scorecard-action-bar">
                            <span className="scorecard-prompt">
                              {currentDoc?.has_optimized_sop || currentDoc?.optimized_scores
                                ? "Current SOP is optimized. Would you like to further refine it with additional recommendations?"
                                : `Would you like to optimize ${currentDoc?.filename || "this SOP"} (Generated automatically in ${currentDoc?.detected_language || "English"})?`}
                            </span>
                            <button className="opt-yes-btn" onClick={() => {
                              setShowOptForm(true);
                              setSelectedSuggestions(suggestions.map((s) => s.id));
                            }}>
                              {currentDoc?.has_optimized_sop || currentDoc?.optimized_scores
                                ? `🔄 Further Optimize (${currentDoc?.detected_language || "English"})`
                                : `✨ Yes, Optimize SOP (${currentDoc?.detected_language || "English"})`}
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* 2. INTERACTIVE OPTIMIZATION CHECKBOX SUGGESTIONS         */}
                    {/* ======================================================== */}
                    {showOptForm && !optResult && (
                      <div className="opt-panel">
                        {optimizing ? (
                          <PipelineProgressBar
                            mode="optimize"
                            progress={optProgress}
                            currentStageIndex={optStageIndex}
                            stageDetail={optStageDetail}
                            title={
                              activeSop?.has_optimized_sop
                                ? `Iterative SOP Refinement & ${currentDoc?.detected_language || "English"} Generation`
                                : `Canonical English Optimization & ${currentDoc?.detected_language || "English"} Generation`
                            }
                            badgeText={activeSop?.has_optimized_sop ? "ITERATIVE REFINEMENT PIPELINE" : "KENVUE MULTILINGUAL RE-ENGINEERING PIPELINE"}
                          />
                        ) : (
                          <>
                            {currentDoc?.has_optimized_sop && (
                              <div style={{
                                marginBottom: "14px",
                                padding: "9px 13px",
                                background: "#eff6ff",
                                border: "1px solid #bfdbfe",
                                borderRadius: "6px",
                                fontSize: "12.5px",
                                color: "#1e40af",
                                display: "flex",
                                alignItems: "center",
                                gap: "8px"
                              }}>
                                <span style={{ fontSize: "16px" }}>🔄</span>
                                <span>
                                  <strong>Iterative Refinement Active:</strong> Further optimizing on top of the canonical English representation ({currentDoc?.optimized_title || currentDoc?.filename}) and automatically generating output in <strong>{currentDoc?.detected_language || "English"}</strong>.
                                </span>
                              </div>
                            )}
                            <div className="opt-panel-head">
                              <h3>{currentDoc?.has_optimized_sop ? `Select Further Improvements for ${currentDoc?.filename || "Current SOP"}` : `Select Improvements for ${currentDoc?.filename || "SOP"}`}</h3>
                              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                {currentDoc?.has_optimized_sop && (
                                  <button
                                    className="select-all-btn"
                                    style={{ background: "#f1f5f9", color: "#475569", border: "1px solid #cbd5e1" }}
                                    onClick={() => {
                                      setShowOptForm(false);
                                      if (currentDoc && (currentDoc.optimized_scores || currentDoc.optimization_report)) {
                                        const rep = currentDoc.optimization_report || {};
                                        setOptResult({
                                          document_id: currentDoc.id,
                                          document_title: currentDoc.optimized_title || rep.document_title || currentDoc.filename,
                                          title: currentDoc.optimized_title || rep.document_title || currentDoc.filename,
                                          previous_scores: rep.previous_scores || currentDoc.scores,
                                          updated_scores: currentDoc.optimized_scores || rep.updated_scores,
                                          output_language: currentDoc.output_language || rep.output_language || currentDoc.detected_language || "English",
                                          detected_language: currentDoc.detected_language || rep.detected_language || "English",
                                          internal_processing_language: "English",
                                          before_and_after_comparison: rep.before_and_after_comparison,
                                          score_difference: rep.score_difference ?? (currentDoc.optimized_scores && currentDoc.scores ? (currentDoc.optimized_scores.average_score - currentDoc.scores.average_score) : 0),
                                          resolved_violations: rep.resolved_violations || [],
                                          newly_introduced_violations: rep.newly_introduced_violations || [],
                                          validation_report: rep.validation_report,
                                          summary: rep.summary || "Optimized SOP generated according to Kenvue standards.",
                                          pdf_download_url: `/conversations/${active.id}/optimized-sop/download?document_id=${currentDoc.id}`,
                                          pdf_preview_url: `/conversations/${active.id}/optimized-sop/preview?document_id=${currentDoc.id}`,
                                          skill_url: `/conversations/${active.id}/optimization-skill?document_id=${currentDoc.id}`,
                                        });
                                      }
                                    }}
                                  >
                                    ✕ Cancel
                                  </button>
                                )}
                                {suggestions.length > 0 && (
                                  <button
                                    className="select-all-btn"
                                    onClick={() => {
                                      if (selectedSuggestions.length === suggestions.length) {
                                        setSelectedSuggestions([]);
                                      } else {
                                        setSelectedSuggestions(suggestions.map((s) => s.id));
                                      }
                                    }}
                                  >
                                    {selectedSuggestions.length === suggestions.length ? "Deselect All" : "Select All"}
                                  </button>
                                )}
                              </div>
                            </div>

                            {suggestions.length > 0 && (
                              <div className="suggestions-list">
                                {suggestions.map((sug) => {
                                  const isChecked = selectedSuggestions.includes(sug.id);
                                  return (
                                    <div
                                      key={sug.id}
                                      className={`suggestion-item ${isChecked ? "selected" : ""}`}
                                      onClick={() => {
                                        setSelectedSuggestions((prev) =>
                                          isChecked ? prev.filter((id) => id !== sug.id) : [...prev, sug.id]
                                        );
                                      }}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={isChecked}
                                        onChange={() => {}} // handled by parent onClick
                                      />
                                      <div className="suggestion-text">
                                        <strong>{sug.title}</strong>
                                        <p>{sug.description}</p>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}

                            <div className="custom-input-box">
                              <label>Custom Changes or Additional Guidelines (Optional)</label>
                              <textarea
                                value={customInstructions}
                                onChange={(e) => setCustomInstructions(e.target.value)}
                                placeholder="Type any specific changes you want made (e.g. 'Add a step to check rotor seal ring', 'Include batch record log format', etc.)..."
                              />
                            </div>

                            <LlmErrorBanner
                              message={optError}
                              onDismiss={() => setOptError("")}
                              onOpenSettings={() => setSettingsOpen(true)}
                              isAdmin={currentUser?.role === "admin"}
                            />

                            <button
                              className="generate-opt-btn"
                              onClick={handleOptimize}
                              disabled={optimizing || (selectedSuggestions.length === 0 && !customInstructions.trim())}
                            >
                              {currentDoc?.has_optimized_sop
                                ? `🚀 Apply Further Changes & Generate ${currentDoc?.detected_language || "English"} PDF (${currentDoc?.filename || "Current SOP"})`
                                : `🚀 Apply Changes & Generate Kenvue Standard PDF in ${currentDoc?.detected_language || "English"} (${currentDoc?.filename || "SOP"})`}
                            </button>
                          </>
                        )}
                      </div>
                    )}

                    {/* ======================================================== */}
                    {/* 3. OPTIMIZED RESULT & BEFORE/AFTER SCORECARD             */}
                    {/* ======================================================== */}
                    {optResult && (
                      <div className="opt-result-card">
                        <div className="opt-result-head">
                          <div>
                            <h3>
                              🎉 Kenvue Standardized SOP Generated in{" "}
                              {getLangMeta(optResult.output_language || currentDoc?.output_language || singleSopOutputLanguage).flag}{" "}
                              {optResult.output_language || currentDoc?.output_language || singleSopOutputLanguage || "English"}!
                            </h3>
                            <div style={{ fontSize: "12px", color: "#475569", marginTop: "4px" }}>
                              Detected Source Language: <strong>{currentDoc?.detected_language || "English"}</strong> ·
                              Internal Processing: <strong>English (NLLB-200 Canonical)</strong> ·
                              Generated Output Language: <strong>{optResult.output_language || currentDoc?.output_language || singleSopOutputLanguage || "English"}</strong>
                            </div>
                          </div>
                          <span style={{ fontSize: "12.5px", fontWeight: 700, color: "#166534" }}>
                            Original SOP & Media Preserved As-Is
                          </span>
                        </div>

                        <div className="comparison-grid">
                          <div className="comp-box">
                            <div className="comp-label">Template Score</div>
                            <div className="comp-scores">
                              <span className="score-prev">{optResult.previous_scores?.template_score}%</span>
                              <span>➔</span>
                              <span className="score-new">{optResult.updated_scores.template_score}%</span>
                            </div>
                            <span className="comp-delta">
                              {optResult.updated_scores.template_score - (optResult.previous_scores?.template_score || 0) >= 0
                                ? `+${optResult.updated_scores.template_score - (optResult.previous_scores?.template_score || 0)}`
                                : `${optResult.updated_scores.template_score - (optResult.previous_scores?.template_score || 0)}`}
                            </span>
                          </div>

                          <div className="comp-box">
                            <div className="comp-label">Readability Score</div>
                            <div className="comp-scores">
                              <span className="score-prev">{optResult.previous_scores?.readability_score}%</span>
                              <span>➔</span>
                              <span className="score-new">{optResult.updated_scores.readability_score}%</span>
                            </div>
                            <span className="comp-delta">
                              {optResult.updated_scores.readability_score - (optResult.previous_scores?.readability_score || 0) >= 0
                                ? `+${optResult.updated_scores.readability_score - (optResult.previous_scores?.readability_score || 0)}`
                                : `${optResult.updated_scores.readability_score - (optResult.previous_scores?.readability_score || 0)}`}
                            </span>
                          </div>

                          <div className="comp-box">
                            <div className="comp-label">Quality Score</div>
                            <div className="comp-scores">
                              <span className="score-prev">{optResult.previous_scores?.quality_score}%</span>
                              <span>➔</span>
                              <span className="score-new">{optResult.updated_scores.quality_score}%</span>
                            </div>
                            <span className="comp-delta">
                              {optResult.updated_scores.quality_score - (optResult.previous_scores?.quality_score || 0) >= 0
                                ? `+${optResult.updated_scores.quality_score - (optResult.previous_scores?.quality_score || 0)}`
                                : `${optResult.updated_scores.quality_score - (optResult.previous_scores?.quality_score || 0)}`}
                            </span>
                          </div>

                          <div className="comp-box" style={{ background: "#f0fdf4", borderColor: "#86efac" }}>
                            <div className="comp-label" style={{ color: "#166534", fontWeight: 700 }}>Overall Compliance</div>
                            <div className="comp-scores">
                              <span className="score-prev">{optResult.previous_scores?.average_score}%</span>
                              <span>➔</span>
                              <span className="score-new" style={{ fontSize: "18px" }}>{optResult.updated_scores.average_score}%</span>
                            </div>
                            <span className="comp-delta">
                              {optResult.updated_scores.average_score - (optResult.previous_scores?.average_score || 0) >= 0
                                ? `+${optResult.updated_scores.average_score - (optResult.previous_scores?.average_score || 0)}`
                                : `${optResult.updated_scores.average_score - (optResult.previous_scores?.average_score || 0)}`}
                            </span>
                          </div>
                        </div>

                        {/* BEFORE-AND-AFTER COMPLIANCE AUDIT REPORT */}
                        {(optResult.resolved_violations?.length > 0 || optResult.newly_introduced_violations?.length > 0 || optResult.before_and_after_comparison) && (
                          <div className="before-after-audit-card">
                            <div className="before-after-header">
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span style={{ fontSize: "18px" }}>📋</span>
                                <div>
                                  <h4 style={{ margin: 0, fontSize: "13.5px", fontWeight: 800, color: "#0f172a" }}>
                                    Kenvue Guideline Compliance Audit &amp; Violation Resolution Report
                                  </h4>
                                  <span style={{ fontSize: "11.5px", color: "#475569" }}>
                                    Verified against official Kenvue Master SOP-WI Template (Standard SOP-STD-001)
                                  </span>
                                </div>
                              </div>
                              {optResult.score_difference !== undefined && (
                                <span className={`audit-delta-tag ${optResult.score_difference >= 0 ? "positive" : "negative"}`}>
                                  {optResult.score_difference >= 0 ? `+${optResult.score_difference}` : optResult.score_difference}% Net Compliance Gain
                                </span>
                              )}
                            </div>

                            {optResult.resolved_violations && optResult.resolved_violations.length > 0 && (
                              <div className="audit-section resolved">
                                <div className="audit-section-title">
                                  <span>✅</span>
                                  <strong>Resolved Violations ({optResult.resolved_violations.length})</strong>
                                </div>
                                <ul className="audit-list">
                                  {optResult.resolved_violations.map((rv, idx) => (
                                    <li key={idx} className="audit-item resolved">
                                      <span className="check-icon">✓</span>
                                      <span><strong>{rv.code || "RULE"}:</strong> {rv.rule || rv.description || (typeof rv === "string" ? rv : JSON.stringify(rv))}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {optResult.newly_introduced_violations && optResult.newly_introduced_violations.length > 0 && (
                              <div className="audit-section newly-introduced">
                                <div className="audit-section-title">
                                  <span>⚠️</span>
                                  <strong>Remaining / Attention Needed ({optResult.newly_introduced_violations.length})</strong>
                                </div>
                                <ul className="audit-list">
                                  {optResult.newly_introduced_violations.map((nv, idx) => (
                                    <li key={idx} className="audit-item remaining">
                                      <span className="warn-icon">!</span>
                                      <span><strong>{nv.code || "RULE"}:</strong> {nv.rule || nv.description || (typeof nv === "string" ? nv : JSON.stringify(nv))}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {optResult.before_and_after_comparison?.passed_checks && optResult.before_and_after_comparison.passed_checks.length > 0 && (
                              <div className="audit-section passed">
                                <div className="audit-section-title">
                                  <span>🛡️</span>
                                  <strong>Verified Kenvue Master Standards ({optResult.before_and_after_comparison.passed_checks.length})</strong>
                                </div>
                                <div className="passed-checks-grid">
                                  {optResult.before_and_after_comparison.passed_checks.map((pc, idx) => (
                                    <div key={idx} className="passed-check-pill">
                                      <span>✓</span> {pc}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        {optResult.validation_report && (
                          <div style={{
                            margin: "12px 0 14px 0",
                            padding: "10px 14px",
                            background: optResult.validation_report.requires_human_review || !optResult.validation_report.passed ? "#fffbeb" : "#f0fdf4",
                            border: optResult.validation_report.requires_human_review || !optResult.validation_report.passed ? "1px solid #fcd34d" : "1px solid #86efac",
                            borderRadius: "6px",
                            fontSize: "12.5px",
                            color: optResult.validation_report.requires_human_review || !optResult.validation_report.passed ? "#92400e" : "#166534",
                          }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: 700 }}>
                              <span>🛡️</span>
                              <span>
                                {optResult.validation_report.requires_human_review || !optResult.validation_report.passed
                                  ? "Author review required: this draft contains unresolved source, template, or requested-change findings."
                                  : "Automated checks passed. Author approval is still required before use."}
                              </span>
                            </div>
                            {optResult.validation_report.verified_custom?.length > 0 && (
                              <div style={{ marginTop: "6px", paddingLeft: "24px", display: "flex", flexDirection: "column", gap: "3px", fontSize: "12px" }}>
                                {optResult.validation_report.verified_custom.map((vc, i) => (
                                  <div key={i} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ color: "#15803d", fontWeight: 800 }}>✓</span>
                                    <span>{vc}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}

                        <div className="opt-download-actions">
                          <a
                            href={`${API}${optResult.pdf_download_url}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="dl-btn"
                          >
                            ⬇️ Download Optimized PDF ({optResult.output_language || currentDoc?.output_language || singleSopOutputLanguage || "English"})
                          </a>
                          <button
                            className="preview-btn"
                            onClick={() => {
                              setPdfPreviewUrl(optResult.pdf_preview_url);
                              setPdfPreviewTitle(
                                `Optimized SOP Preview (${optResult.output_language || currentDoc?.output_language || singleSopOutputLanguage || "English"})`
                              );
                              setPdfPreviewOpen(true);
                            }}
                          >
                            👁️ Preview Optimized PDF
                          </button>
                          {currentDoc?.id && (
                            <button
                              type="button"
                              className="further-opt-btn"
                              onClick={() => {
                                const isDocx = (currentDoc.filename || "").toLowerCase().endsWith(".docx");
                                if (isDocx) {
                                  window.open(`${API}/conversations/${active.id}/sop/${currentDoc.id}/original-pdf?download=true`, "_blank");
                                } else {
                                  setPdfPreviewUrl(`/conversations/${active.id}/sop/${currentDoc.id}/original-pdf`);
                                  setPdfPreviewTitle(
                                    `Preserved Original Uploaded SOP (${currentDoc.original_language || currentDoc.detected_language || "Original"})`
                                  );
                                  setPdfPreviewOpen(true);
                                }
                              }}
                            >
                              {(currentDoc.filename || "").toLowerCase().endsWith(".docx")
                                ? `⬇️ Download Original Uploaded DOCX (${currentDoc.original_language || currentDoc.detected_language || "Original"})`
                                : `📄 View Original Uploaded SOP (${currentDoc.original_language || currentDoc.detected_language || "Original"})`}
                            </button>
                          )}
                          {optResult.skill_url && (
                            <a
                              href={`${API}${optResult.skill_url}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="further-opt-btn"
                              title="Inspect compiled optimization skill directive"
                              style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
                            >
                              📜 View Skill Directive
                            </a>
                          )}
                          <button
                            className="further-opt-btn"
                            onClick={() => {
                              setOptResult(null);
                              setShowOptForm(true);
                              setCustomInstructions("");
                              setSelectedSuggestions(suggestions.map((s) => s.id));
                            }}
                          >
                            🔄 Further Optimize
                          </button>
                          <button
                            className="end-chat-btn"
                            onClick={handleEndChat}
                            style={{ marginLeft: "auto" }}
                          >
                            🏁 End Chat & Archive
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Messages list */}
                    {messages.map((m, i) => (
                      <div className={`row ${m.role}`} key={i}>
                        <div className="bubble">
                          {m.role === "assistant" ? (
                            <div
                              className="formatted-message"
                              dangerouslySetInnerHTML={{ __html: formatMessageContent(m.content) }}
                            />
                          ) : (
                            <div className="user-message-text">{m.content}</div>
                          )}
                          {m.referenced_pages?.length > 0 && (
                            <div className="rag-citation-footer">
                              <span className="rag-citation">
                                📌 Grounded in SOP Page{m.referenced_pages.length > 1 ? "s" : ""}:{" "}
                                {m.referenced_pages.sort((a, b) => a - b).join(", ")}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}

                    {loading && (
                      <div className="row assistant">
                        <div className="bubble">Consulting SOP guidelines & generating answer...</div>
                      </div>
                    )}

                    {chatError && activeSop && (
                      <div style={{ maxWidth: "820px", width: "100%", margin: "0 auto" }}>
                        <LlmErrorBanner
                          message={chatError}
                          onDismiss={clearAllLlmErrors}
                          onOpenSettings={() => setSettingsOpen(true)}
                          isAdmin={currentUser?.role === "admin"}
                        />
                      </div>
                    )}
                  </div>

                  {/* Input Composer */}
                  <div
                    className="composer"
                    style={
                      activeLlmUnavailableError
                        ? { background: "#fef2f2", borderTop: "1px solid #fecaca" }
                        : undefined
                    }
                  >
                    <textarea
                      value={input}
                      disabled={Boolean(activeLlmUnavailableError)}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          send();
                        }
                      }}
                      style={
                        activeLlmUnavailableError
                          ? { background: "#fff1f2", color: "#991b1b", cursor: "not-allowed", opacity: 0.85 }
                          : undefined
                      }
                      placeholder={
                        activeLlmUnavailableError
                          ? "🔌 Chat is disabled while the LLM service is unavailable. Verify LLM configuration or click 'Dismiss & Retry LLM Connection' above."
                          : activeSop
                          ? "Ask questions or request modifications to this procedure..."
                          : "Type a message or upload an SOP..."
                      }
                    />
                    <button
                      onClick={send}
                      disabled={loading || !input.trim() || Boolean(activeLlmUnavailableError)}
                      title={activeLlmUnavailableError ? "Chat disabled while LLM service is unavailable" : "Send message"}
                    >
                      {activeLlmUnavailableError ? "LLM Offline" : "Send"}
                    </button>
                  </div>
                </>
              )}
            </section>
          </>
        )}
      </main>

      {/* PDF PREVIEW MODAL */}
      {pdfPreviewOpen && (pdfPreviewUrl || optResult || activeHarmonizedVersion) && (
        <div className="modal-overlay" onClick={() => setPdfPreviewOpen(false)}>
          <div className="modal-content" style={{ width: "min(950px, 95vw)", height: "90vh" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{pdfPreviewTitle || (optResult ? "Optimized SOP Preview (ReportLab PDF)" : "Harmonized SOP Preview")}</h2>
              <button className="modal-close" onClick={() => setPdfPreviewOpen(false)}>✕</button>
            </div>
            <div style={{ flex: 1, padding: "10px" }}>
              <iframe
                src={`${API}${pdfPreviewUrl || optResult?.pdf_preview_url || activeHarmonizedVersion?.preview_url}`}
                style={{ width: "100%", height: "100%", border: 0, borderRadius: "8px" }}
                title="SOP Preview"
              />
            </div>
          </div>
        </div>
      )}

      {/* ARTIFACTS GALLERY MODAL (MinIO images & tables) */}
      {artifactsModalOpen && (
        <div className="modal-overlay" onClick={() => setArtifactsModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Docling Extracted Media ({artifacts.length})</h2>
              <button className="modal-close" onClick={() => setArtifactsModalOpen(false)}>✕</button>
            </div>
            <div className="modal-filters">
              <button
                className={`filter-btn ${artifactFilter === "all" ? "active" : ""}`}
                onClick={() => setArtifactFilter("all")}
              >
                All ({artifacts.length})
              </button>
              <button
                className={`filter-btn ${artifactFilter === "image" ? "active" : ""}`}
                onClick={() => setArtifactFilter("image")}
              >
                Images ({artifacts.filter((a) => a.artifact_type === "image").length})
              </button>
              <button
                className={`filter-btn ${artifactFilter === "table" ? "active" : ""}`}
                onClick={() => setArtifactFilter("table")}
              >
                Tables ({artifacts.filter((a) => a.artifact_type === "table").length})
              </button>
            </div>
            <div className="modal-body">
              {filteredArtifacts.map((art) => (
                <div className="artifact-card" key={art.id}>
                  <div className="artifact-img-box">
                    <img src={`${API}${art.preview_url}`} alt={art.caption} loading="lazy" />
                  </div>
                  <div className="artifact-info">
                    <div className="artifact-tag">
                      {art.artifact_type === "table" ? "📊 Structured Table" : "🖼️ Source Figure"}
                    </div>
                    <div className="artifact-caption">{art.caption}</div>
                    <div className="artifact-meta">Page {art.page} · Preserved for re-insertion</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
