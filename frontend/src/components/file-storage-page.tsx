"use client";

import { Download, FileText, Trash2, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { API_URL, authFetch, authJson } from "@/lib/api";
import { supabase } from "@/lib/supabase";

import styles from "./marketing-home.module.css";

type StoredFile = { id: string; filename: string; source_zip: string | null; size_bytes: number; uploaded_at: string; uploaded_by: string | null };
type UploadResult = { saved: StoredFile[]; skipped: { filename: string; reason: string }[] };

// The API takes up to 200 MB per request; larger selections go up in several requests.
const BATCH_BYTES = 190 * 1024 * 1024;

const size = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
const when = (value: string) => new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });

function batches(files: File[]): File[][] {
  const groups: File[][] = [];
  let current: File[] = [];
  let total = 0;
  for (const file of files) {
    if (current.length && total + file.size > BATCH_BYTES) {
      groups.push(current);
      current = [];
      total = 0;
    }
    current.push(file);
    total += file.size;
  }
  if (current.length) groups.push(current);
  return groups;
}

/** POST with upload progress (fetch cannot report it). */
async function send(files: File[], onProgress: (loaded: number) => void): Promise<UploadResult> {
  const { data } = await supabase().auth.getSession();
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}/api/v1/files`);
    if (data.session) request.setRequestHeader("Authorization", `Bearer ${data.session.access_token}`);
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onload = () => {
      let parsed: (UploadResult & { detail?: unknown }) | null = null;
      try { parsed = JSON.parse(request.responseText); } catch { /* not JSON */ }
      if (request.status >= 200 && request.status < 300 && parsed) resolve(parsed);
      else reject(new Error(typeof parsed?.detail === "string" ? parsed.detail : `Upload failed: ${request.status}`));
    };
    request.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
    request.send(body);
  });
}

export function FileStoragePage() {
  const router = useRouter();
  const { session, account, loading } = useAccount();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<StoredFile[] | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<UploadResult["skipped"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [zipping, setZipping] = useState(false);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    if (!loading && !session) router.replace(`/get-started?mode=login&next=${encodeURIComponent("/files")}`);
  }, [loading, router, session]);

  const load = useCallback(() => authJson<StoredFile[]>("/api/v1/files").then(setFiles)
    .catch((failure) => setError(failure instanceof Error ? failure.message : "Could not load your files.")), []);
  useEffect(() => { if (account?.can_upload_files) load(); }, [account, load]);

  async function upload(selected: File[]) {
    const accepted = selected.filter((file) => /\.(pdf|zip)$/i.test(file.name));
    const rejected = selected.filter((file) => !accepted.includes(file)).map((file) => ({ filename: file.name, reason: "only PDF and zip files can be uploaded" }));
    const tooBig = accepted.filter((file) => file.size > BATCH_BYTES).map((file) => ({ filename: file.name, reason: "larger than 190 MB; split it into smaller zips" }));
    const queue = accepted.filter((file) => file.size <= BATCH_BYTES);
    setError(null);
    setNotice(null);
    setSkipped([...rejected, ...tooBig]);
    if (!queue.length) return;
    const total = queue.reduce((sum, file) => sum + file.size, 0);
    let done = 0;
    let saved = 0;
    try {
      for (const group of batches(queue)) {
        const result = await send(group, (loaded) => setProgress(`Uploading… ${Math.min(100, Math.round(((done + loaded) / total) * 100))}%`));
        done += group.reduce((sum, file) => sum + file.size, 0);
        saved += result.saved.length;
        setSkipped((current) => [...current, ...result.skipped]);
      }
      setNotice(`${saved} PDF${saved === 1 ? "" : "s"} uploaded.`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Upload failed.");
    } finally {
      setProgress(null);
      if (input.current) input.current.value = "";
      load();
    }
  }

  function save(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }

  async function download(file: StoredFile) {
    setError(null);
    const response = await authFetch(`${API_URL}/api/v1/files/${file.id}/download`);
    if (!response.ok) {
      setError(`Could not download ${file.filename}.`);
      return;
    }
    save(await response.blob(), file.filename);
  }

  async function downloadAll() {
    setError(null);
    setZipping(true);
    try {
      const response = await authFetch(`${API_URL}/api/v1/files/download-all`);
      if (!response.ok) throw new Error();
      const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? "files.zip";
      save(await response.blob(), name);
    } catch {
      setError("Could not download the files. Try again shortly.");
    } finally {
      setZipping(false);
    }
  }

  async function remove(file: StoredFile) {
    if (!window.confirm(`Delete ${file.filename}? This cannot be undone.`)) return;
    setError(null);
    const response = await authFetch(`${API_URL}/api/v1/files/${file.id}`, { method: "DELETE" });
    if (!response.ok && response.status !== 404) setError(`Could not delete ${file.filename}.`);
    setFiles((current) => current?.filter((item) => item.id !== file.id) ?? null);
  }

  async function removeAll() {
    if (!files?.length || !account) return;
    const count = `${files.length} file${files.length === 1 ? "" : "s"}`;
    const whose = account.is_developer && files.some((file) => file.uploaded_by && file.uploaded_by !== account.email)
      ? ", including files uploaded by other users" : "";
    if (!window.confirm(`Delete all ${count}${whose}? This cannot be undone.`)) return;
    setError(null);
    setNotice(null);
    setClearing(true);
    try {
      const result = await authJson<{ deleted: number }>("/api/v1/files", { method: "DELETE" });
      setNotice(`${result.deleted} file${result.deleted === 1 ? "" : "s"} deleted.`);
    } catch {
      setError("Could not delete the files. Try again shortly.");
    } finally {
      setClearing(false);
      load();
    }
  }

  const totalSize = files?.reduce((sum, file) => sum + file.size_bytes, 0) ?? 0;

  return <div className={styles.root}>
    <SiteHeader active="none"/>
    <main className="account-page container">
      <span className="eyebrow">{account?.is_developer ? "DEVELOPER" : "FILE UPLOADS"}</span>
      <h1>File storage</h1>
      {!account ? <p className="account-muted">{loading ? "Loading…" : "We could not load your account. Try again shortly."}</p>
        : !account.can_upload_files ? <p className="account-muted">File storage is not available on this account.</p> : <>
          <p className="file-intro">{account.is_developer
            ? "Private PDF storage. You see every file, including those uploaded by file uploaders. Upload PDFs, or a zip of PDFs to add many at once."
            : "Upload PDFs, or a zip of PDFs to add many at once. Only you and the site's developers can see your files."}</p>
          <div className={dragging ? "file-drop is-dragging" : "file-drop"}
            onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); if (!progress) upload(Array.from(event.dataTransfer.files)); }}>
            <Upload aria-hidden/>
            <p>{progress ?? "Drag PDFs or zip files here"}</p>
            <input ref={input} type="file" accept=".pdf,.zip,application/pdf,application/zip" multiple hidden
              onChange={(event) => upload(Array.from(event.target.files ?? []))}/>
            <button type="button" className="site-button button-outline" disabled={Boolean(progress)} onClick={() => input.current?.click()}>Choose files</button>
            <span className="account-muted">PDFs up to 50 MB each. Zips are unpacked and only their PDFs are kept.</span>
          </div>
          {notice && <p className="form-notice" role="status">{notice}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          {skipped.length > 0 && <div className="form-error" role="status">
            <strong>Not uploaded ({skipped.length})</strong>
            <ul className="file-skipped">{skipped.map((item, index) => <li key={`${item.filename}-${index}`}>{item.filename}: {item.reason}</li>)}</ul>
          </div>}
          <div className="file-list-head">
            <h2>{account.is_developer ? "All files" : "Your files"}</h2>
            {files && files.length > 0 && <div className="file-list-actions">
              <span className="account-muted">{files.length} file{files.length === 1 ? "" : "s"} · {size(totalSize)}</span>
              <button type="button" className="site-button button-outline" disabled={zipping} onClick={downloadAll}>
                <Download aria-hidden/>{zipping ? "Preparing zip…" : "Download all"}
              </button>
              <button type="button" className="site-button button-outline" disabled={clearing || Boolean(progress)} onClick={removeAll}>
                <Trash2 aria-hidden/>{clearing ? "Deleting…" : "Delete all"}
              </button>
            </div>}
          </div>
          {!files ? <p className="account-muted">Loading…</p> : !files.length ? <p className="account-muted">No files yet.</p>
            : <ul className="file-list">{files.map((file) => <li key={file.id}>
              <FileText aria-hidden/>
              <div className="file-meta">
                <span className="file-name">{file.filename}</span>
                <span className="account-muted">{size(file.size_bytes)} · {when(file.uploaded_at)}{file.source_zip ? ` · from ${file.source_zip}` : ""}{account.is_developer && file.uploaded_by && file.uploaded_by !== account.email ? ` · uploaded by ${file.uploaded_by}` : ""}</span>
              </div>
              <button type="button" className="site-button button-ghost" aria-label={`Download ${file.filename}`} onClick={() => download(file)}><Download/></button>
              <button type="button" className="site-button button-ghost" aria-label={`Delete ${file.filename}`} onClick={() => remove(file)}><Trash2/></button>
            </li>)}</ul>}
        </>}
    </main>
    <SiteFooter/>
  </div>;
}
