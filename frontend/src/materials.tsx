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

export function MaterialsLibrary() {
  const { identity, logout, authorizationHeader, handleUnauthenticated } = useAuth();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  async function downloadMaterial(material: Material) {
    const headers = authorizationHeader();
    if (!headers) {
      handleUnauthenticated();
      return;
    }
    try {
      const response = await fetch(`/api/materials/${encodeURIComponent(material.id)}/download`, { headers });
      if (!response.ok) {
        if (response.status === 401) handleUnauthenticated();
        const body: unknown = await response.json();
        setError(errorMessage(body, "Unable to download material"));
        return;
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = material.original_filename;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      setError("Unable to reach the server");
    }
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
        <div className="material-grid">
          {materials.map((material) => (
            <article className="material-card" key={material.id}>
              <div className="material-card-topline"><span className="file-type">{material.content_type}</span><span>{formatBytes(material.byte_size)}</span></div>
              <div className="file-symbol" aria-hidden="true">FILE</div>
              <h3>{material.title}</h3>
              <p className="filename">{material.original_filename}</p>
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
