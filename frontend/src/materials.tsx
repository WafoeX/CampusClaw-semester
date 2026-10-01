import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth, type Identity } from "./auth";

type Material = {
  id: string;
  title: string;
  original_filename: string;
  content_type: string;
  byte_size: number;
  sha256: string;
  uploader_id: string;
  created_at: string;
  retrieval_status?: "pending" | "processing" | "searchable" | "unsupported" | "failed";
};

type RetrievalMode = "keyword" | "vector" | "hybrid";
type KnowledgeSource = {
  source_id: string;
  material_id: string;
  title: string;
  original_filename: string;
  excerpt: string;
  page: number | null;
  line_start: number | null;
  line_end: number | null;
  section: string | null;
  action: string;
};
type KnowledgeResponse = {
  status: "answered" | "insufficient_evidence";
  answer: string | null;
  citations: string[];
  sources: KnowledgeSource[];
  requested_mode: RetrievalMode;
  effective_mode: RetrievalMode | "keyword_only";
};

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      return String(detail.message);
    }
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function LibraryHeader({ identity, logout }: { identity: Identity; logout: () => Promise<void> }) {
  return (
    <header className="page-header page-hero">
      <div className="page-title-group">
        <p className="eyebrow">CLASS LIBRARY</p>
        <h1>Materials</h1>
        <p className="muted account-line">
          <span className="online-dot" aria-hidden="true" />
          {identity.account}
          <span className="role-badge">{identity.role}</span>
        </p>
      </div>
      <div className="header-actions">
        {identity.role === "teacher" && <Link className="button" to="/materials/upload">上传资料</Link>}
        <button type="button" onClick={() => void logout()}>退出登录</button>
      </div>
    </header>
  );
}

function AnswerText({ answer }: { answer: string }) {
  const pieces = answer.split(/(\[S[1-9][0-9]{0,2}\])/g);
  return <p className="knowledge-answer">{pieces.map((piece, index) => {
    const match = /^\[S[1-9][0-9]{0,2}\]$/.test(piece);
    const sourceId = piece.slice(1, -1);
    return match ? <a
      key={`${piece}-${index}`}
      href={`#source-${sourceId}`}
      onClick={(event) => {
        event.preventDefault();
        const target = document.getElementById(`source-${sourceId}`);
        target?.focus();
        target?.scrollIntoView?.({ block: "nearest" });
      }}
    >{piece}</a> : <span key={`${piece}-${index}`}>{piece}</span>;
  })}</p>;
}

export function MaterialsLibrary() {
  const { identity, logout, authorizationHeader, handleUnauthenticated } = useAuth();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeQuestion, setKnowledgeQuestion] = useState("");
  const [knowledgeMode, setKnowledgeMode] = useState<RetrievalMode>("hybrid");
  const [knowledgeResult, setKnowledgeResult] = useState<KnowledgeResponse | null>(null);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);

  const loadMaterials = useCallback(async () => {
    const headers = authorizationHeader();
    if (!headers) {
      handleUnauthenticated();
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/materials", { headers });
      const body: unknown = await response.json();
      if (!response.ok) {
        if (response.status === 401) handleUnauthenticated();
        setError(errorMessage(body, "Unable to load materials"));
        return;
      }
      setMaterials(body as Material[]);
    } catch {
      setError("Unable to reach the server");
    } finally {
      setLoading(false);
    }
  }, [authorizationHeader, handleUnauthenticated]);

  useEffect(() => {
    void loadMaterials();
  }, [loadMaterials]);

  async function submitKnowledge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = knowledgeQuestion.trim();
    if (!question) {
      setKnowledgeError("请输入问题。");
      setKnowledgeResult(null);
      return;
    }
    const headers = authorizationHeader();
    if (!headers) {
      handleUnauthenticated();
      return;
    }
    setKnowledgeLoading(true);
    setKnowledgeError(null);
    setKnowledgeResult(null);
    try {
      const response = await fetch("/api/knowledge/query", {
        method: "POST",
        headers: { ...headers, "content-type": "application/json" },
        body: JSON.stringify({ question, result_limit: 10, mode: knowledgeMode }),
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        if (response.status === 401) handleUnauthenticated();
        setKnowledgeError(errorMessage(body, "知识库问答暂时不可用。"));
        return;
      }
      setKnowledgeResult(body as KnowledgeResponse);
    } catch {
      setKnowledgeError("暂时无法连接知识库服务。");
    } finally {
      setKnowledgeLoading(false);
    }
  }

  async function downloadAuthorized(
    action: string,
    filename: string,
    reportError: (message: string) => void,
  ) {
    const headers = authorizationHeader();
    if (!headers) {
      handleUnauthenticated();
      return;
    }
    try {
      const response = await fetch(action, { headers });
      if (!response.ok) {
        if (response.status === 401) handleUnauthenticated();
        const body: unknown = await response.json();
        reportError(errorMessage(body, "Unable to download material"));
        return;
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      reportError("Unable to reach the server");
    }
  }

  async function downloadMaterial(material: Material) {
    await downloadAuthorized(
      `/api/materials/${encodeURIComponent(material.id)}/download`,
      material.original_filename,
      setError,
    );
  }

  async function downloadKnowledgeSource(source: KnowledgeSource) {
    const expectedAction = `/api/materials/${encodeURIComponent(source.material_id)}/download`;
    if (source.action !== expectedAction) {
      setKnowledgeError("来源地址无效。");
      return;
    }
    await downloadAuthorized(expectedAction, source.original_filename, setKnowledgeError);
  }

  if (!identity) return null;
  return (
    <main className="page-shell">
      <LibraryHeader identity={identity} logout={logout} />
      <section className="library-panel" aria-labelledby="library-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">YOUR CLASS</p>
            <h2 id="library-heading">Teaching materials</h2>
            <p className="section-description">浏览并下载当前班级共享的课程资料。</p>
          </div>
          <button type="button" className="secondary-button" onClick={() => void loadMaterials()} disabled={loading}>
            <span aria-hidden="true">↻</span> {loading ? "刷新中…" : "刷新"}
          </button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {loading && <p className="status-card" role="status">正在加载课程资料…</p>}
        {!loading && !error && materials.length === 0 && <p className="empty-state"><span aria-hidden="true">◇</span> 当前班级还没有可用资料。</p>}
        <section className="knowledge-panel" aria-labelledby="knowledge-heading">
          <div className="section-heading">
            <div>
              <p className="eyebrow">GROUNDED ANSWERS</p>
              <h2 id="knowledge-heading">知识库问答</h2>
              <p className="section-description">仅根据当前班级已检索资料回答，每次提问相互独立。</p>
            </div>
          </div>
          <form className="knowledge-form" onSubmit={submitKnowledge} aria-label="知识库问答表单">
            <label htmlFor="knowledge-question">问题</label>
            <textarea id="knowledge-question" value={knowledgeQuestion} onChange={(event) => setKnowledgeQuestion(event.target.value)} maxLength={2000} rows={3} />
            <div className="knowledge-controls">
              <label htmlFor="knowledge-mode">检索方式</label>
              <select id="knowledge-mode" value={knowledgeMode} onChange={(event) => setKnowledgeMode(event.target.value as RetrievalMode)}>
                <option value="hybrid">混合检索（默认）</option>
                <option value="keyword">关键词</option>
                <option value="vector">语义向量</option>
              </select>
              <button className="primary-button" type="submit" disabled={knowledgeLoading}>{knowledgeLoading ? "回答中…" : "提交问题"}</button>
            </div>
          </form>
          {knowledgeError && <p className="error" role="alert">{knowledgeError}</p>}
          {knowledgeLoading && <p className="status-card" role="status">正在检索本班资料…</p>}
          {knowledgeResult && <article className="knowledge-result" aria-live="polite">
            {knowledgeResult.effective_mode === "keyword_only" && <p className="degraded-notice" role="status">语义检索暂不可用，已降级为关键词检索。</p>}
            {knowledgeResult.status === "insufficient_evidence" ? <p className="knowledge-refusal">根据本班资料无法回答该问题</p> : knowledgeResult.answer && <AnswerText answer={knowledgeResult.answer} />}
            {knowledgeResult.sources.length > 0 && <div className="knowledge-sources" aria-label="回答来源">
              {knowledgeResult.sources.map((source) => <article className="source-card" id={`source-${source.source_id}`} key={source.source_id} tabIndex={-1}>
                <h3>{source.source_id} · {source.title}</h3>
                <p className="filename">{source.original_filename}</p>
                <p>{source.excerpt}</p>
                <p className="muted">{source.page ? `第 ${source.page} 页` : `第 ${source.line_start}–${source.line_end} 行`}{source.section ? ` · ${source.section}` : ""}</p>
                <button className="download-link" type="button" onClick={() => void downloadKnowledgeSource(source)}>打开授权资料 <span aria-hidden="true">↓</span></button>
              </article>)}
            </div>}
          </article>}
        </section>
        <div className="material-grid">
          {materials.map((material) => (
            <article className="material-card" key={material.id}>
              <div className="material-card-topline"><span className="file-type">{material.content_type}</span><span>{formatBytes(material.byte_size)}</span></div>
              <div className="file-symbol" aria-hidden="true">FILE</div>
              <h3>{material.title}</h3>
              <p className="filename">{material.original_filename}</p>
              <p className="muted">检索状态：{material.retrieval_status === "searchable" ? "可检索" : material.retrieval_status === "processing" ? "处理中" : material.retrieval_status === "unsupported" ? "暂不支持检索" : material.retrieval_status === "failed" ? "索引失败" : "等待索引"}</p>
              <dl className="metadata-list">
                <div><dt>Uploaded</dt><dd>{new Date(material.created_at).toLocaleString()}</dd></div>
                <div><dt>Uploader</dt><dd>{material.uploader_id}</dd></div>
              </dl>
              <button className="download-link" type="button" onClick={() => void downloadMaterial(material)}>
                下载文件 <span aria-hidden="true">↓</span>
              </button>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

export function UploadPage() {
  const { identity, authorizationHeader, handleUnauthenticated } = useAuth();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!identity) return null;
  if (identity.role !== "teacher") return <Navigate to="/materials" replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!title.trim() || !file) {
      setError("A title and one file are required.");
      return;
    }
    const headers = authorizationHeader();
    if (!headers) {
      handleUnauthenticated();
      return;
    }
    setSubmitting(true);
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
    try {
      const response = await fetch("/api/materials", {
        method: "POST",
        headers,
        body: form,
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        if (response.status === 401) handleUnauthenticated();
        setError(errorMessage(body, response.status === 413 ? "File is too large" : "Upload failed"));
        return;
      }
      navigate("/materials", { replace: true });
    } catch {
      setError("Unable to reach the server");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page-shell upload-page">
      <header className="page-header page-hero compact-hero">
        <div className="page-title-group"><p className="eyebrow">CLASS LIBRARY</p><h1>Upload material</h1><p className="muted">将新的教学资料分享给当前班级。</p></div>
        <Link className="secondary-button light-button" to="/materials">返回资料库</Link>
      </header>
      <form className="upload-card" onSubmit={submit} aria-label="Upload material form">
        <div className="upload-card-heading">
          <span className="upload-icon" aria-hidden="true">↑</span>
          <div>
            <p className="eyebrow">NEW MATERIAL</p>
            <h2>Material details</h2>
            <p className="muted">The material will be shared with your current class.</p>
          </div>
        </div>
        <label>
          Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} aria-describedby="upload-help" />
        </label>
        <label>
          File
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <p id="upload-help" className="form-help">One file per upload. Files are downloaded as attachments.</p>
        {error && <p className="error" role="alert">{error}</p>}
        {submitting && <p className="status-inline" role="status">正在安全上传文件…</p>}
        <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "上传中…" : "上传资料"}</button>
      </form>
    </main>
  );
}
