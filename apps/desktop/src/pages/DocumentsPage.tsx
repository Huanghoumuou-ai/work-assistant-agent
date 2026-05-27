import { Fragment, useEffect, useRef, useState } from "react";
import { AlertTriangle, Archive, Clock3, Database, FilePlus2, FileText, FileUp, Lightbulb, ListChecks, PlayCircle, RefreshCw, RotateCcw, Scissors, SlidersHorizontal, Trash2, XCircle } from "lucide-react";

import {
  batchCancelPipelineJobs,
  batchRetryPipelineJobs,
  cancelPipelineJob,
  chunkDocument,
  createTextDocument,
  deleteDocument,
  getDocuments,
  getPipelineJobEvents,
  getPipelineJobs,
  getPipelineStatus,
  getProvidersStatus,
  indexDocument,
  parseDocument,
  pipelineEventsStreamUrl,
  processMissingDocuments,
  reprocessDocumentPipeline,
  retryPipelineJob,
  triggerDocumentPipeline,
  updatePipelineJobPriority,
  updateDocumentStatus,
  uploadDocument,
} from "../api/documents.api";
import { generateMemorySuggestionsFromDocument } from "../api/memory.api";
import { getProjects } from "../api/projects.api";
import type { DocumentItem, DocumentStatus, PipelineJob, PipelineJobEvent, PipelineJobStatus, PipelineStatus, ProjectItem, ProvidersStatus } from "../types/api";
import { formatDate } from "../utils/formatDate";
import { formatFileSize } from "../utils/formatFileSize";

const PAGE_SIZE = 10;

type BusyAction =
  | "upload"
  | "text"
  | "refresh"
  | "batch"
  | "batchCancel"
  | "batchRetry"
  | `pipeline:${string}`
  | `events:${string}`
  | `cancel:${string}`
  | `retry:${string}`
  | `reprocess:${string}`
  | `priority:${string}`
  | `parse:${string}`
  | `chunk:${string}`
  | `index:${string}`
  | `suggest:${string}`
  | `status:${string}`
  | `delete:${string}`
  | null;

export function DocumentsPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const lastPipelineEventIdRef = useRef<string | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [pipelineJobs, setPipelineJobs] = useState<Record<string, PipelineJob>>({});
  const [recentPipelineJobs, setRecentPipelineJobs] = useState<PipelineJob[]>([]);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [jobEvents, setJobEvents] = useState<Record<string, PipelineJobEvent[]>>({});
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [pipelineStatusFilter, setPipelineStatusFilter] = useState<"" | PipelineJobStatus>("");
  const [providersStatus, setProvidersStatus] = useState<ProvidersStatus | null>(null);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [projectFilter, setProjectFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | DocumentStatus>("");
  const [uploadProjectId, setUploadProjectId] = useState("");
  const [textProjectId, setTextProjectId] = useState("");
  const [textTitle, setTextTitle] = useState("");
  const [textContent, setTextContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<BusyAction>(null);
  const [dragActive, setDragActive] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const providerRisk = providersStatus && !providersStatus.embedding.configured ? providersStatus.embedding.reason ?? "Embedding provider is not configured." : null;

  const loadProjects = async () => {
    try {
      const response = await getProjects();
      setProjects(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load projects");
    }
  };

  const loadDocuments = async (nextOffset = offset, options: { clearMessage?: boolean; silent?: boolean } = {}) => {
    if (!options.silent) {
      setLoading(true);
    }
    try {
      const response = await getDocuments({
        limit: PAGE_SIZE,
        offset: nextOffset,
        projectId: projectFilter || undefined,
        status: statusFilter || undefined,
      });
      setDocuments(response.data.items);
      setTotal(response.data.total);
      if (options.clearMessage) {
        setMessage(null);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load documents");
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  };

  const loadPipelineJobs = async () => {
    const response = await getPipelineJobs({ limit: 100, offset: 0 });
    const latestByDocument: Record<string, PipelineJob> = {};
    for (const job of response.data.items) {
      const current = latestByDocument[job.document_id];
      if (!current || Date.parse(job.created_at) > Date.parse(current.created_at)) {
        latestByDocument[job.document_id] = job;
      }
    }
    setRecentPipelineJobs(response.data.items);
    setPipelineJobs(latestByDocument);
    return latestByDocument;
  };

  const loadPipelineStatus = async () => {
    try {
      const response = await getPipelineStatus();
      setPipelineStatus(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load pipeline status");
    }
  };

  const loadProvidersStatus = async () => {
    try {
      const response = await getProvidersStatus();
      setProvidersStatus(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load provider status");
    }
  };

  const resetAndLoad = () => {
    setOffset(0);
  };

  const queuePipeline = async (documentId: string, label: string) => {
    setMessage(`Queueing pipeline for ${label}`);
    const response = await triggerDocumentPipeline(documentId);
    setPipelineJobs((current) => ({ ...current, [documentId]: response.data }));
    return response.data;
  };

  const refreshPipelineState = async () => {
    await Promise.all([loadPipelineJobs(), loadPipelineStatus()]);
  };

  const uploadFiles = async (files: FileList | File[]) => {
    const selectedFiles = Array.from(files);
    if (selectedFiles.length === 0 || busyAction) {
      return;
    }

    setBusyAction("upload");
    setMessage(null);
    try {
      let indexedFiles = 0;
      for (const [index, file] of selectedFiles.entries()) {
        const position = selectedFiles.length > 1 ? ` (${index + 1}/${selectedFiles.length})` : "";
        setMessage(`Uploading ${file.name}${position}`);
        const uploaded = await uploadDocument(file, uploadProjectId || undefined);
        await queuePipeline(uploaded.data.id, `${file.name}${position}`);
        indexedFiles += 1;
      }
      setOffset(0);
      await Promise.all([loadDocuments(0), refreshPipelineState()]);
      setMessage(`Queued pipeline for ${indexedFiles} file${indexedFiles > 1 ? "s" : ""}`);
    } catch (error) {
      await loadDocuments(0);
      setMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setBusyAction(null);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  };

  const addPastedText = async () => {
    const cleanContent = textContent.trim();
    if (!cleanContent || busyAction) {
      setMessage("Paste text content before adding it to the knowledge base");
      return;
    }

    setBusyAction("text");
    setMessage("Saving pasted text");
    try {
      const created = await createTextDocument({
        title: textTitle.trim() || null,
        content: cleanContent,
        project_id: textProjectId || undefined,
      });
      await queuePipeline(created.data.id, "pasted text");
      setTextTitle("");
      setTextContent("");
      setOffset(0);
      await Promise.all([loadDocuments(0), refreshPipelineState()]);
      setMessage("Queued pipeline for pasted text");
    } catch (error) {
      await loadDocuments(0);
      setMessage(error instanceof Error ? error.message : "Failed to add pasted text");
    } finally {
      setBusyAction(null);
    }
  };

  const runPipeline = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("Archived documents cannot be processed");
      return;
    }

    setBusyAction(`pipeline:${document.id}`);
    setMessage(null);
    try {
      const job = await queuePipeline(document.id, document.original_filename);
      await Promise.all([loadDocuments(undefined, { silent: true }), refreshPipelineState()]);
      setMessage(`Pipeline ${job.status}: ${document.original_filename}`);
    } catch (error) {
      await loadDocuments(undefined, { silent: true });
      setMessage(error instanceof Error ? error.message : "Pipeline request failed");
    } finally {
      setBusyAction(null);
    }
  };

  const cancelPipeline = async (job: PipelineJob) => {
    setBusyAction(`cancel:${job.id}`);
    setMessage(null);
    try {
      const response = await cancelPipelineJob(job.id);
      setPipelineJobs((current) => ({ ...current, [response.data.document_id]: response.data }));
      await refreshPipelineState();
      setMessage(response.data.status === "canceled" ? "Pipeline canceled" : "Cancel requested; the current step will finish first");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cancel failed");
    } finally {
      setBusyAction(null);
    }
  };

  const retryPipeline = async (job: PipelineJob) => {
    setBusyAction(`retry:${job.id}`);
    setMessage(null);
    try {
      const response = await retryPipelineJob(job.id);
      setPipelineJobs((current) => ({ ...current, [response.data.document_id]: response.data }));
      await refreshPipelineState();
      setMessage("Pipeline retry queued");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Retry failed");
    } finally {
      setBusyAction(null);
    }
  };

  const toggleJobEvents = async (job: PipelineJob) => {
    if (expandedJobId === job.id) {
      setExpandedJobId(null);
      return;
    }
    setExpandedJobId(job.id);
    if (jobEvents[job.id]) {
      return;
    }
    setBusyAction(`events:${job.id}`);
    try {
      const response = await getPipelineJobEvents(job.id);
      setJobEvents((current) => ({ ...current, [job.id]: response.data.items }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load job events");
    } finally {
      setBusyAction(null);
    }
  };

  const changeJobPriority = async (job: PipelineJob) => {
    if (job.status !== "queued") {
      setMessage("Only queued pipeline jobs can change priority");
      return;
    }
    const value = window.prompt("Set queued job priority. Higher values run first.", String(job.priority));
    if (value === null) {
      return;
    }
    const priority = Number(value);
    if (!Number.isInteger(priority)) {
      setMessage("Priority must be an integer");
      return;
    }
    setBusyAction(`priority:${job.id}`);
    try {
      const response = await updatePipelineJobPriority(job.id, priority);
      setPipelineJobs((current) => ({ ...current, [response.data.document_id]: response.data }));
      await refreshPipelineState();
      setMessage("Pipeline priority updated");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Priority update failed");
    } finally {
      setBusyAction(null);
    }
  };

  const reprocessPipeline = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("Archived documents cannot be reprocessed");
      return;
    }

    await reprocessPipelineById(document.id);
  };

  const reprocessPipelineById = async (documentId: string) => {
    setBusyAction(`reprocess:${documentId}`);
    setMessage(null);
    try {
      const response = await reprocessDocumentPipeline(documentId);
      setPipelineJobs((current) => ({ ...current, [documentId]: response.data }));
      await refreshPipelineState();
      setMessage("Pipeline reprocess queued");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reprocess failed");
    } finally {
      setBusyAction(null);
    }
  };

  const processMissing = async () => {
    setBusyAction("batch");
    setMessage(null);
    try {
      const response = await processMissingDocuments(projectFilter || undefined);
      await refreshPipelineState();
      setMessage(`Queued ${response.data.total} missing document pipeline${response.data.total === 1 ? "" : "s"}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Batch process failed");
    } finally {
      setBusyAction(null);
    }
  };

  const batchCancelVisible = async () => {
    const jobs = visiblePipelineJobs.filter((job) => job.status === "queued" || job.status === "running").slice(0, 100);
    if (!jobs.length) {
      setMessage("No visible active pipeline jobs to cancel");
      return;
    }
    setBusyAction("batchCancel");
    setMessage(null);
    try {
      const response = await batchCancelPipelineJobs({ job_ids: jobs.map((job) => job.id) });
      for (const job of response.data.items) {
        setPipelineJobs((current) => ({ ...current, [job.document_id]: job }));
      }
      await refreshPipelineState();
      setMessage(`Canceled ${response.data.acted} pipeline job${response.data.acted === 1 ? "" : "s"}${response.data.skipped ? `, skipped ${response.data.skipped}` : ""}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Batch cancel failed");
    } finally {
      setBusyAction(null);
    }
  };

  const batchRetryVisible = async () => {
    const jobs = visiblePipelineJobs.filter((job) => job.status === "failed" || job.status === "canceled").slice(0, 100);
    if (!jobs.length) {
      setMessage("No visible failed or canceled jobs to retry");
      return;
    }
    setBusyAction("batchRetry");
    setMessage(null);
    try {
      const response = await batchRetryPipelineJobs({ job_ids: jobs.map((job) => job.id) });
      for (const job of response.data.items) {
        setPipelineJobs((current) => ({ ...current, [job.document_id]: job }));
      }
      await refreshPipelineState();
      setMessage(`Retried ${response.data.acted} pipeline job${response.data.acted === 1 ? "" : "s"}${response.data.skipped ? `, skipped ${response.data.skipped}` : ""}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Batch retry failed");
    } finally {
      setBusyAction(null);
    }
  };

  const changeStatus = async (document: DocumentItem) => {
    const nextStatus: DocumentStatus = document.status === "archived" ? "uploaded" : "archived";
    setBusyAction(`status:${document.id}`);
    setMessage(null);
    try {
      await updateDocumentStatus(document.id, nextStatus);
      await loadDocuments();
      setMessage(nextStatus === "archived" ? "Document archived" : "Document restored");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Status update failed");
    } finally {
      setBusyAction(null);
    }
  };

  const runParse = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("Archived documents cannot be parsed");
      return;
    }

    setBusyAction(`parse:${document.id}`);
    setMessage(null);
    try {
      await parseDocument(document.id);
      await loadDocuments();
      setMessage("Document parsed");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Parse failed");
      await loadDocuments();
    } finally {
      setBusyAction(null);
    }
  };

  const runChunk = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed") {
      setMessage("Only uploaded and parsed documents can be chunked");
      return;
    }

    setBusyAction(`chunk:${document.id}`);
    setMessage(null);
    try {
      await chunkDocument(document.id);
      await loadDocuments();
      setMessage("Document chunked");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Chunking failed");
      await loadDocuments();
    } finally {
      setBusyAction(null);
    }
  };

  const runIndex = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed" || document.chunk_result?.status !== "chunked") {
      setMessage("Only uploaded, parsed, and chunked documents can be indexed");
      return;
    }

    setBusyAction(`index:${document.id}`);
    setMessage(null);
    try {
      const response = await indexDocument(document.id);
      setDocuments((current) =>
        current.map((item) => (item.id === document.id ? { ...item, embedding_result: response.data } : item)),
      );
      await loadDocuments();
      setMessage(`Document indexed: ${response.data.indexed_chunk_count} vectors`);
    } catch (error) {
      await loadDocuments();
      const errorMessage = error instanceof Error ? error.message : "Indexing failed";
      setMessage(
        errorMessage.includes("OPENAI_API_KEY")
          ? `${errorMessage} For local smoke testing, set EMBEDDING_PROVIDER=fake in .env and restart the backend.`
          : errorMessage,
      );
    } finally {
      setBusyAction(null);
    }
  };

  const suggestFromDocument = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed") {
      setMessage("Only uploaded and parsed documents can generate suggestions");
      return;
    }

    setBusyAction(`suggest:${document.id}`);
    setMessage(null);
    try {
      const response = await generateMemorySuggestionsFromDocument(document.id, 5, true);
      setMessage(`Generated ${response.data.total} pending work suggestion${response.data.total === 1 ? "" : "s"} for Memory review`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Suggestion generation failed");
    } finally {
      setBusyAction(null);
    }
  };

  const removeDocument = async (document: DocumentItem) => {
    const confirmed = window.confirm(
      `Permanently delete "${document.original_filename}"? This will delete the database record and the original file.`,
    );
    if (!confirmed) {
      return;
    }

    setBusyAction(`delete:${document.id}`);
    setMessage(null);
    try {
      await deleteDocument(document.id);
      const shouldStepBack = documents.length === 1 && offset > 0;
      const nextOffset = shouldStepBack ? Math.max(0, offset - PAGE_SIZE) : offset;
      if (nextOffset !== offset) {
        setOffset(nextOffset);
      }
      await loadDocuments(nextOffset);
      setMessage("Document deleted");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Delete failed");
    } finally {
      setBusyAction(null);
    }
  };

  useEffect(() => {
    void Promise.all([loadProjects(), refreshPipelineState(), loadProvidersStatus()]);
  }, []);

  useEffect(() => {
      void loadDocuments(offset, { clearMessage: true });
  }, [offset, projectFilter, statusFilter]);

  useEffect(() => {
    const hasActiveJob = Object.values(pipelineJobs).some((job) => job.status === "queued" || job.status === "running");
    if (!hasActiveJob) {
      return;
    }
    const timer = window.setInterval(() => {
      void Promise.all([
        refreshPipelineState(),
        loadDocuments(offset, { silent: true }),
      ]);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [pipelineJobs, offset, projectFilter, statusFilter]);

  useEffect(() => {
    const source = new EventSource(pipelineEventsStreamUrl(lastPipelineEventIdRef.current ?? undefined));
    source.addEventListener("pipeline_event", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent<string>).data) as PipelineJobEvent;
        lastPipelineEventIdRef.current = parsed.id;
        setJobEvents((current) => {
          const existing = current[parsed.job_id] ?? [];
          if (existing.some((item) => item.id === parsed.id)) {
            return current;
          }
          return { ...current, [parsed.job_id]: [...existing, parsed] };
        });
        void refreshPipelineState();
      } catch {
        // Keep the polling fallback in control if a stream event is malformed.
      }
    });
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, []);

  const visiblePipelineJobs = pipelineStatusFilter
    ? recentPipelineJobs.filter((job) => job.status === pipelineStatusFilter)
    : recentPipelineJobs;
  const activeVisibleCount = visiblePipelineJobs.filter((job) => job.status === "queued" || job.status === "running").length;
  const retryableVisibleCount = visiblePipelineJobs.filter((job) => job.status === "failed" || job.status === "canceled").length;
  const documentNameById = new Map(documents.map((document) => [document.id, document.original_filename]));

  return (
    <section className="page">
      <header className="page-header row-header">
        <div>
          <p className="eyebrow">Phase 15</p>
          <h1>Documents</h1>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={() => {
            setBusyAction("refresh");
            void Promise.all([loadProjects(), loadDocuments(), refreshPipelineState(), loadProvidersStatus()]).finally(() => setBusyAction(null));
          }}
          title="Refresh documents"
          disabled={busyAction !== null}
        >
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="filters-row">
        <label>
          <span>Upload Project</span>
          <select value={uploadProjectId} onChange={(event) => setUploadProjectId(event.target.value)} disabled={busyAction !== null}>
            <option value="">Unfiled</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Filter Project</span>
          <select
            value={projectFilter}
            onChange={(event) => {
              setProjectFilter(event.target.value);
              resetAndLoad();
            }}
            disabled={busyAction !== null}
          >
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as "" | DocumentStatus);
              resetAndLoad();
            }}
            disabled={busyAction !== null}
          >
            <option value="">All statuses</option>
            <option value="uploaded">Uploaded</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      </div>

      {providerRisk ? (
        <div className="provider-warning">
          <AlertTriangle size={18} />
          <span>
            Index provider risk: {providerRisk} Open Settings / Provider Diagnostics before running large batches.
          </span>
        </div>
      ) : null}

      <div
        className={dragActive ? "drop-zone active" : "drop-zone"}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setDragActive(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          void uploadFiles(event.dataTransfer.files);
        }}
      >
        <FileUp size={28} />
        <div>
          <strong>{busyAction === "upload" ? "Processing file" : "Drop files here"}</strong>
          <span>Files are saved locally, then automatically parsed, chunked, and indexed into the vector database.</span>
        </div>
        <button className="secondary-button" type="button" onClick={() => inputRef.current?.click()} disabled={busyAction !== null}>
          Choose Files
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) {
              void uploadFiles(event.target.files);
            }
          }}
        />
      </div>

      <div className="text-ingest-panel">
        <div className="text-ingest-heading">
          <FilePlus2 size={20} />
          <div>
            <strong>Paste text into knowledge base</strong>
            <span>Save copied notes, rules, or requirements as a local text document, then automatically parse, chunk, and index it.</span>
          </div>
        </div>
        <div className="text-ingest-grid">
          <label>
            <span>Title</span>
            <input value={textTitle} onChange={(event) => setTextTitle(event.target.value)} placeholder="Optional title, e.g. Meeting notes" disabled={busyAction !== null} />
          </label>
          <label>
            <span>Project</span>
            <select value={textProjectId} onChange={(event) => setTextProjectId(event.target.value)} disabled={busyAction !== null}>
              <option value="">Unfiled</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-ingest-content">
            <span>Text</span>
            <textarea value={textContent} onChange={(event) => setTextContent(event.target.value)} placeholder="Paste copied text here..." disabled={busyAction !== null} />
          </label>
          <button className="secondary-button" type="button" onClick={() => void addPastedText()} disabled={busyAction !== null || !textContent.trim()}>
            <Database size={16} />
            <span>{busyAction === "text" ? "Processing" : "Add to Knowledge Base"}</span>
          </button>
        </div>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel pipeline-jobs-panel">
        <div className="table-heading pipeline-heading">
          <div>
            <strong>Pipeline Jobs</strong>
            <span>
              {pipelineStatus
                ? `${pipelineStatus.active_count} active · ${pipelineStatus.failed_count} failed · worker ${pipelineStatus.worker_running ? "online" : "offline"} · stale ${pipelineStatus.stale_running_count}`
                : "Loading status"}
            </span>
          </div>
          <div className="pipeline-toolbar">
            <select value={pipelineStatusFilter} onChange={(event) => setPipelineStatusFilter(event.target.value as "" | PipelineJobStatus)} disabled={busyAction !== null}>
              <option value="">All jobs</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="canceled">Canceled</option>
            </select>
            <button className="secondary-button" type="button" onClick={() => void processMissing()} disabled={busyAction !== null}>
              <ListChecks size={16} />
              <span>{busyAction === "batch" ? "Queueing" : "Process missing documents"}</span>
            </button>
            <button className="secondary-button danger" type="button" onClick={() => void batchCancelVisible()} disabled={busyAction !== null || activeVisibleCount === 0}>
              <XCircle size={16} />
              <span>{busyAction === "batchCancel" ? "Canceling" : `Cancel active (${activeVisibleCount})`}</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void batchRetryVisible()} disabled={busyAction !== null || retryableVisibleCount === 0}>
              <RotateCcw size={16} />
              <span>{busyAction === "batchRetry" ? "Retrying" : `Retry failed (${retryableVisibleCount})`}</span>
            </button>
            <button className="icon-button" type="button" onClick={() => void refreshPipelineState()} title="Refresh pipeline jobs" disabled={busyAction !== null}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        {visiblePipelineJobs.length === 0 ? (
          <div className="empty-panel compact">No pipeline jobs found</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Step</th>
                <th>Progress</th>
                <th>Updated</th>
                <th>Error</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {visiblePipelineJobs.slice(0, 12).map((job) => {
                const active = job.status === "queued" || job.status === "running";
                const stale = job.status === "running" && job.lock_expires_at !== null && Date.parse(job.lock_expires_at) <= Date.now();
                return (
                  <Fragment key={job.id}>
                    <tr>
                      <td>
                        <strong>{documentNameById.get(job.document_id) ?? job.document_id}</strong>
                        <span>{job.document_id}</span>
                      </td>
                      <td>
                        <strong className={`status-text ${active ? "pending" : job.status}`}>{stale ? "stale" : job.status}</strong>
                        {job.cancel_requested ? <span>cancel requested</span> : null}
                        {job.locked_by ? <span>{job.locked_by}</span> : null}
                      </td>
                      <td>
                        <strong>{job.priority}</strong>
                        <span>
                          attempt {job.attempt_count}/{job.max_attempts}
                        </span>
                      </td>
                      <td>{job.current_step ?? "-"}</td>
                      <td>
                        <span>{job.progress_percent}%</span>
                        <div className="progress-track">
                          <div style={{ width: `${job.progress_percent}%` }} />
                        </div>
                      </td>
                      <td>{formatDate(job.updated_at)}</td>
                      <td>
                        <span>{job.error_message ? `${job.last_error_code ? `${job.last_error_code}: ` : ""}${job.error_message}${job.current_step === "index" ? " · Open Settings diagnostics" : ""}` : "-"}</span>
                      </td>
                      <td>
                        <div className="action-group">
                          <button className="icon-button small" type="button" title="Show job events" onClick={() => void toggleJobEvents(job)} disabled={busyAction !== null}>
                            <Clock3 size={16} />
                          </button>
                          {job.status === "queued" ? (
                            <button className="icon-button small" type="button" title="Set priority" onClick={() => void changeJobPriority(job)} disabled={busyAction !== null}>
                              <SlidersHorizontal size={16} />
                            </button>
                          ) : null}
                          {active ? (
                            <button className="icon-button small danger" type="button" title="Cancel pipeline" onClick={() => void cancelPipeline(job)} disabled={busyAction !== null}>
                              <XCircle size={16} />
                            </button>
                          ) : null}
                          {job.status === "failed" || job.status === "canceled" ? (
                            <button className="icon-button small" type="button" title="Retry pipeline" onClick={() => void retryPipeline(job)} disabled={busyAction !== null}>
                              <RotateCcw size={16} />
                            </button>
                          ) : null}
                          {job.status === "succeeded" ? (
                            <button className="icon-button small" type="button" title="Reprocess document" onClick={() => void reprocessPipelineById(job.document_id)} disabled={busyAction !== null}>
                              <ListChecks size={16} />
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                    {expandedJobId === job.id ? (
                      <tr className="pipeline-events-row">
                        <td colSpan={8}>
                          {busyAction === `events:${job.id}` ? (
                            <span>Loading events</span>
                          ) : jobEvents[job.id]?.length ? (
                            <div className="pipeline-event-list">
                              {jobEvents[job.id].map((event) => (
                                <div key={event.id} className="pipeline-event-item">
                                  <strong>{event.event_type}</strong>
                                  <span>{event.step ?? "job"}</span>
                                  <span>{event.message ?? "-"}</span>
                                  <time>{formatDate(event.created_at)}</time>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span>No events recorded</span>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="table-panel">
        <div className="table-heading">
          <strong>Uploaded Documents</strong>
          <span>{loading ? "Loading" : `${total} total`}</span>
        </div>
        {documents.length === 0 ? (
          <div className="empty-panel compact">{loading ? "Loading documents" : "No documents found"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Size</th>
                <th>Status</th>
                <th>Parse</th>
                <th>Chunks</th>
                <th>Index</th>
                <th>Pipeline</th>
                <th>Uploaded</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => {
                const statusBusy = busyAction === `status:${document.id}`;
                const parseBusy = busyAction === `parse:${document.id}`;
                const chunkBusy = busyAction === `chunk:${document.id}`;
                const indexBusy = busyAction === `index:${document.id}`;
                const deleteBusy = busyAction === `delete:${document.id}`;
                const parseResult = document.parse_result;
                const chunkResult = document.chunk_result;
                const embeddingResult = document.embedding_result;
                const pipelineJob = pipelineJobs[document.id];
                const canChunk = document.status === "uploaded" && parseResult?.status === "parsed";
                const canIndex = canChunk && chunkResult?.status === "chunked";
                const canSuggest = document.status === "uploaded" && parseResult?.status === "parsed";
                const pipelineBusy = busyAction === `pipeline:${document.id}`;
                const pipelineActive = pipelineJob?.status === "queued" || pipelineJob?.status === "running";
                const pipelineCancelBusy = pipelineJob ? busyAction === `cancel:${pipelineJob.id}` : false;
                const pipelineRetryBusy = pipelineJob ? busyAction === `retry:${pipelineJob.id}` : false;
                const pipelineReprocessBusy = busyAction === `reprocess:${document.id}`;
                const suggestBusy = busyAction === `suggest:${document.id}`;
                return (
                  <tr key={document.id}>
                    <td>
                      <strong>{document.original_filename}</strong>
                      <span>{document.relative_path}</span>
                    </td>
                    <td>{document.extension}</td>
                    <td>{formatFileSize(document.size_bytes)}</td>
                    <td>
                      <span className={`status-pill ${document.status}`}>{document.status}</span>
                    </td>
                    <td>
                      <strong className={`status-text ${parseBusy ? "pending" : parseResult?.status ?? "idle"}`}>
                        {parseBusy ? "parsing" : parseResult?.status ?? "not parsed"}
                      </strong>
                      {parseResult ? (
                        <span>
                          {parseResult.status === "parsed"
                            ? `${parseResult.char_count} chars${parseResult.truncated ? ", truncated" : ""}`
                            : parseResult.error_message ?? "failed"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${chunkBusy ? "pending" : chunkResult?.status ?? "idle"}`}>
                        {chunkBusy ? "chunking" : chunkResult?.status ?? "not chunked"}
                      </strong>
                      {chunkResult ? (
                        <span>
                          {chunkResult.status === "chunked"
                            ? `${chunkResult.chunk_count} chunks${chunkResult.truncated ? ", truncated" : ""}`
                            : chunkResult.error_message ?? "failed"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${indexBusy ? "pending" : embeddingResult?.status ?? "idle"}`}>
                        {indexBusy ? "indexing" : embeddingResult?.status ?? "not indexed"}
                      </strong>
                      {embeddingResult ? (
                        <span>
                          {embeddingResult.status === "indexed"
                            ? `${embeddingResult.indexed_chunk_count} vectors, ${embeddingResult.provider}`
                            : embeddingResult.error_message ?? "failed"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${pipelineBusy || pipelineActive ? "pending" : pipelineJob?.status ?? "idle"}`}>
                        {pipelineBusy ? "queueing" : pipelineJob?.status ?? "not queued"}
                      </strong>
                      {pipelineJob ? (
                        <>
                          <span>
                            {pipelineJob.status === "running" && pipelineJob.current_step
                              ? `${pipelineJob.current_step} · ${pipelineJob.progress_percent}%`
                              : pipelineJob.status === "failed"
                                ? `${pipelineJob.error_message ?? "failed"}${pipelineJob.current_step === "index" ? " · Open Settings diagnostics" : ""}`
                                : pipelineJob.status === "canceled"
                                  ? "canceled"
                                  : pipelineJob.status === "succeeded"
                                    ? "done · 100%"
                                    : `waiting · ${pipelineJob.progress_percent}%`}
                          </span>
                          <div className="progress-track" aria-label={`Pipeline progress ${pipelineJob.progress_percent}%`}>
                            <div style={{ width: `${pipelineJob.progress_percent}%` }} />
                          </div>
                        </>
                      ) : null}
                    </td>
                    <td>{formatDate(document.created_at)}</td>
                    <td>
                      <div className="action-group">
                        {pipelineJob?.status === "queued" || pipelineJob?.status === "running" ? (
                          <button
                            className="icon-button small danger"
                            type="button"
                            title={pipelineJob.status === "queued" ? "Cancel queued pipeline" : "Request cancel after current step"}
                            onClick={() => void cancelPipeline(pipelineJob)}
                            disabled={busyAction !== null}
                          >
                            <XCircle size={16} />
                          </button>
                        ) : pipelineJob?.status === "failed" || pipelineJob?.status === "canceled" ? (
                          <button
                            className="icon-button small"
                            type="button"
                            title="Retry pipeline"
                            onClick={() => void retryPipeline(pipelineJob)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <RotateCcw size={16} />
                          </button>
                        ) : pipelineJob?.status === "succeeded" ? (
                          <button
                            className="icon-button small"
                            type="button"
                            title="Reprocess document pipeline"
                            onClick={() => void reprocessPipeline(document)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <ListChecks size={16} />
                          </button>
                        ) : (
                          <button
                            className="icon-button small"
                            type="button"
                            title={document.status === "archived" ? "Archived documents cannot be processed" : "Process document pipeline"}
                            onClick={() => void runPipeline(document)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <PlayCircle size={16} />
                          </button>
                        )}
                        <button
                          className="icon-button small"
                          type="button"
                          title={document.status === "archived" ? "Archived documents cannot be parsed" : "Parse document"}
                          onClick={() => void runParse(document)}
                          disabled={busyAction !== null || document.status === "archived"}
                        >
                          <FileText size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canChunk ? "Chunk document" : "Parse the uploaded document before chunking"}
                          onClick={() => void runChunk(document)}
                          disabled={busyAction !== null || !canChunk}
                        >
                          <Scissors size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canIndex ? "Index document" : "Chunk the parsed document before indexing"}
                          onClick={() => void runIndex(document)}
                          disabled={busyAction !== null || !canIndex}
                        >
                          <Database size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canSuggest ? "Generate pending Memory suggestions from this document" : "Parse the uploaded document before suggesting memories"}
                          onClick={() => void suggestFromDocument(document)}
                          disabled={busyAction !== null || !canSuggest}
                        >
                          <Lightbulb size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={document.status === "archived" ? "Restore document" : "Archive document"}
                          onClick={() => void changeStatus(document)}
                          disabled={busyAction !== null}
                        >
                          {document.status === "archived" ? <RotateCcw size={16} /> : <Archive size={16} />}
                        </button>
                        <button
                          className="icon-button small danger"
                          type="button"
                          title="Permanently delete document"
                          onClick={() => void removeDocument(document)}
                          disabled={busyAction !== null}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                      {pipelineBusy || pipelineCancelBusy || pipelineRetryBusy || pipelineReprocessBusy || parseBusy || chunkBusy || indexBusy || suggestBusy || statusBusy || deleteBusy ? (
                        <span>
                          {pipelineBusy
                            ? "Queueing"
                            : pipelineCancelBusy
                              ? "Canceling"
                              : pipelineRetryBusy
                                ? "Retrying"
                                : pipelineReprocessBusy
                                  ? "Reprocessing"
                                  : parseBusy
                                    ? "Parsing"
                                    : chunkBusy
                                      ? "Chunking"
                                      : indexBusy
                                        ? "Indexing"
                                        : suggestBusy
                                          ? "Suggesting"
                                          : statusBusy
                                            ? "Updating"
                                            : "Deleting"}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="pagination-row">
          <button
            className="secondary-button"
            type="button"
            disabled={offset === 0 || busyAction !== null || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <span>
            Page {page} of {totalPages}
          </span>
          <button
            className="secondary-button"
            type="button"
            disabled={offset + PAGE_SIZE >= total || busyAction !== null || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
