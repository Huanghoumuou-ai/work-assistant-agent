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
import { formatCount, labelChunkStatus, labelDocumentStatus, labelEmbeddingStatus, labelParseStatus, labelPipelineEventType, labelPipelineStatus, labelPipelineStep } from "../utils/labels";

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
  const providerRisk = providersStatus && !providersStatus.embedding.configured ? providersStatus.embedding.reason ?? "Embedding Provider 尚未配置。" : null;

  const loadProjects = async () => {
    try {
      const response = await getProjects();
      setProjects(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "项目加载失败");
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
      setMessage(error instanceof Error ? error.message : "资料加载失败");
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
      setMessage(error instanceof Error ? error.message : "处理流水线状态加载失败");
    }
  };

  const loadProvidersStatus = async () => {
    try {
      const response = await getProvidersStatus();
      setProvidersStatus(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "服务商状态加载失败");
    }
  };

  const resetAndLoad = () => {
    setOffset(0);
  };

  const queuePipeline = async (documentId: string, label: string) => {
    setMessage(`正在为 ${label} 加入处理队列`);
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
        setMessage(`正在上传 ${file.name}${position}`);
        const uploaded = await uploadDocument(file, uploadProjectId || undefined);
        await queuePipeline(uploaded.data.id, `${file.name}${position}`);
        indexedFiles += 1;
      }
      setOffset(0);
      await Promise.all([loadDocuments(0), refreshPipelineState()]);
      setMessage(`已为 ${indexedFiles} 个文件加入处理队列`);
    } catch (error) {
      await loadDocuments(0);
      setMessage(error instanceof Error ? error.message : "上传失败");
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
      setMessage("请先粘贴文字内容，再加入知识库");
      return;
    }

    setBusyAction("text");
    setMessage("正在保存粘贴文字");
    try {
      const created = await createTextDocument({
        title: textTitle.trim() || null,
        content: cleanContent,
        project_id: textProjectId || undefined,
      });
      await queuePipeline(created.data.id, "粘贴文字");
      setTextTitle("");
      setTextContent("");
      setOffset(0);
      await Promise.all([loadDocuments(0), refreshPipelineState()]);
      setMessage("已为粘贴文字加入处理队列");
    } catch (error) {
      await loadDocuments(0);
      setMessage(error instanceof Error ? error.message : "粘贴文字保存失败");
    } finally {
      setBusyAction(null);
    }
  };

  const runPipeline = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("已归档资料不能处理");
      return;
    }

    setBusyAction(`pipeline:${document.id}`);
    setMessage(null);
    try {
      const job = await queuePipeline(document.id, document.original_filename);
      await Promise.all([loadDocuments(undefined, { silent: true }), refreshPipelineState()]);
      setMessage(`处理流水线${labelPipelineStatus(job.status)}：${document.original_filename}`);
    } catch (error) {
      await loadDocuments(undefined, { silent: true });
      setMessage(error instanceof Error ? error.message : "处理请求失败");
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
      setMessage(response.data.status === "canceled" ? "处理任务已取消" : "已请求取消；当前步骤完成后会停止");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "取消失败");
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
      setMessage("处理任务重试已排队");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重试失败");
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
      setMessage(error instanceof Error ? error.message : "任务事件加载失败");
    } finally {
      setBusyAction(null);
    }
  };

  const changeJobPriority = async (job: PipelineJob) => {
    if (job.status !== "queued") {
      setMessage("只有排队中的处理任务可以调整优先级");
      return;
    }
    const value = window.prompt("设置排队任务优先级。数字越大越先执行。", String(job.priority));
    if (value === null) {
      return;
    }
    const priority = Number(value);
    if (!Number.isInteger(priority)) {
      setMessage("优先级必须是整数");
      return;
    }
    setBusyAction(`priority:${job.id}`);
    try {
      const response = await updatePipelineJobPriority(job.id, priority);
      setPipelineJobs((current) => ({ ...current, [response.data.document_id]: response.data }));
      await refreshPipelineState();
      setMessage("处理任务优先级已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "优先级更新失败");
    } finally {
      setBusyAction(null);
    }
  };

  const reprocessPipeline = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("已归档资料不能重新处理");
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
      setMessage("重新处理已排队");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重新处理失败");
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
      setMessage(`已补排 ${response.data.total} 个缺失资料的处理任务`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量处理失败");
    } finally {
      setBusyAction(null);
    }
  };

  const batchCancelVisible = async () => {
    const jobs = visiblePipelineJobs.filter((job) => job.status === "queued" || job.status === "running").slice(0, 100);
    if (!jobs.length) {
      setMessage("当前视图没有可取消的活动处理任务");
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
      setMessage(`已取消 ${response.data.acted} 个处理任务${response.data.skipped ? `，跳过 ${response.data.skipped} 个` : ""}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量取消失败");
    } finally {
      setBusyAction(null);
    }
  };

  const batchRetryVisible = async () => {
    const jobs = visiblePipelineJobs.filter((job) => job.status === "failed" || job.status === "canceled").slice(0, 100);
    if (!jobs.length) {
      setMessage("当前视图没有可重试的失败或已取消任务");
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
      setMessage(`已重试 ${response.data.acted} 个处理任务${response.data.skipped ? `，跳过 ${response.data.skipped} 个` : ""}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量重试失败");
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
      setMessage(nextStatus === "archived" ? "资料已归档" : "资料已恢复");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "状态更新失败");
    } finally {
      setBusyAction(null);
    }
  };

  const runParse = async (document: DocumentItem) => {
    if (document.status !== "uploaded") {
      setMessage("已归档资料不能解析");
      return;
    }

    setBusyAction(`parse:${document.id}`);
    setMessage(null);
    try {
      await parseDocument(document.id);
      await loadDocuments();
      setMessage("资料已解析");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "解析失败");
      await loadDocuments();
    } finally {
      setBusyAction(null);
    }
  };

  const runChunk = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed") {
      setMessage("只有已上传且已解析的资料可以切块");
      return;
    }

    setBusyAction(`chunk:${document.id}`);
    setMessage(null);
    try {
      await chunkDocument(document.id);
      await loadDocuments();
      setMessage("资料已切块");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "切块失败");
      await loadDocuments();
    } finally {
      setBusyAction(null);
    }
  };

  const runIndex = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed" || document.chunk_result?.status !== "chunked") {
      setMessage("只有已上传、已解析且已切块的资料可以索引");
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
      setMessage(`资料已索引：${response.data.indexed_chunk_count} 个向量`);
    } catch (error) {
      await loadDocuments();
      const errorMessage = error instanceof Error ? error.message : "索引失败";
      setMessage(
        errorMessage.includes("OPENAI_API_KEY")
          ? `${errorMessage} 本地冒烟测试可在 .env 设置 EMBEDDING_PROVIDER=fake 后重启后端。`
          : errorMessage,
      );
    } finally {
      setBusyAction(null);
    }
  };

  const suggestFromDocument = async (document: DocumentItem) => {
    if (document.status !== "uploaded" || document.parse_result?.status !== "parsed") {
      setMessage("只有已上传且已解析的资料可以生成建议");
      return;
    }

    setBusyAction(`suggest:${document.id}`);
    setMessage(null);
    try {
      const response = await generateMemorySuggestionsFromDocument(document.id, 5, true);
      setMessage(`已生成 ${response.data.total} 条待审核工作建议`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "建议生成失败");
    } finally {
      setBusyAction(null);
    }
  };

  const removeDocument = async (document: DocumentItem) => {
    const confirmed = window.confirm(
      `永久删除“${document.original_filename}”？这会删除数据库记录和原始文件。`,
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
      setMessage("资料已删除");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
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
          <p className="eyebrow">资料处理</p>
          <h1>资料库</h1>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={() => {
            setBusyAction("refresh");
            void Promise.all([loadProjects(), loadDocuments(), refreshPipelineState(), loadProvidersStatus()]).finally(() => setBusyAction(null));
          }}
          title="刷新资料"
          disabled={busyAction !== null}
        >
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="filters-row">
        <label>
          <span>上传项目</span>
          <select value={uploadProjectId} onChange={(event) => setUploadProjectId(event.target.value)} disabled={busyAction !== null}>
            <option value="">未归档</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>筛选项目</span>
          <select
            value={projectFilter}
            onChange={(event) => {
              setProjectFilter(event.target.value);
              resetAndLoad();
            }}
            disabled={busyAction !== null}
          >
            <option value="">全部项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>状态</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as "" | DocumentStatus);
              resetAndLoad();
            }}
            disabled={busyAction !== null}
          >
            <option value="">全部状态</option>
            <option value="uploaded">已上传</option>
            <option value="archived">已归档</option>
          </select>
        </label>
      </div>

      {providerRisk ? (
        <div className="provider-warning">
          <AlertTriangle size={18} />
          <span>
            索引服务商风险：{providerRisk} 批量处理前请打开设置里的服务商诊断。
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
          <strong>{busyAction === "upload" ? "正在处理文件" : "拖放文件到这里"}</strong>
          <span>文件会保存在本地，然后自动解析、切块并索引到向量库。</span>
        </div>
        <button className="secondary-button" type="button" onClick={() => inputRef.current?.click()} disabled={busyAction !== null}>
          选择文件
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
            <strong>粘贴文字到知识库</strong>
            <span>把复制的笔记、规则或需求保存为本地文字资料，然后自动解析、切块并索引。</span>
          </div>
        </div>
        <div className="text-ingest-grid">
          <label>
            <span>标题</span>
            <input value={textTitle} onChange={(event) => setTextTitle(event.target.value)} placeholder="可选标题，例如会议纪要" disabled={busyAction !== null} />
          </label>
          <label>
            <span>项目</span>
            <select value={textProjectId} onChange={(event) => setTextProjectId(event.target.value)} disabled={busyAction !== null}>
              <option value="">未归档</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-ingest-content">
            <span>文字</span>
            <textarea value={textContent} onChange={(event) => setTextContent(event.target.value)} placeholder="在这里粘贴复制的文字..." disabled={busyAction !== null} />
          </label>
          <button className="secondary-button" type="button" onClick={() => void addPastedText()} disabled={busyAction !== null || !textContent.trim()}>
            <Database size={16} />
            <span>{busyAction === "text" ? "处理中" : "加入知识库"}</span>
          </button>
        </div>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel pipeline-jobs-panel">
        <div className="table-heading pipeline-heading">
          <div>
            <strong>处理任务</strong>
            <span>
              {pipelineStatus
                ? `${pipelineStatus.active_count} 个活动 · ${pipelineStatus.failed_count} 个失败 · 工作器 ${pipelineStatus.worker_running ? "在线" : "离线"} · 过期 ${pipelineStatus.stale_running_count}`
                : "正在加载状态"}
            </span>
          </div>
          <div className="pipeline-toolbar">
            <select value={pipelineStatusFilter} onChange={(event) => setPipelineStatusFilter(event.target.value as "" | PipelineJobStatus)} disabled={busyAction !== null}>
              <option value="">全部任务</option>
              <option value="queued">排队中</option>
              <option value="running">运行中</option>
              <option value="succeeded">已完成</option>
              <option value="failed">失败</option>
              <option value="canceled">已取消</option>
            </select>
            <button className="secondary-button" type="button" onClick={() => void processMissing()} disabled={busyAction !== null}>
              <ListChecks size={16} />
              <span>{busyAction === "batch" ? "排队中" : "处理缺失资料"}</span>
            </button>
            <button className="secondary-button danger" type="button" onClick={() => void batchCancelVisible()} disabled={busyAction !== null || activeVisibleCount === 0}>
              <XCircle size={16} />
              <span>{busyAction === "batchCancel" ? "取消中" : `取消活动任务（${activeVisibleCount}）`}</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void batchRetryVisible()} disabled={busyAction !== null || retryableVisibleCount === 0}>
              <RotateCcw size={16} />
              <span>{busyAction === "batchRetry" ? "重试中" : `重试失败任务（${retryableVisibleCount}）`}</span>
            </button>
            <button className="icon-button" type="button" onClick={() => void refreshPipelineState()} title="刷新处理任务" disabled={busyAction !== null}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        {visiblePipelineJobs.length === 0 ? (
          <div className="empty-panel compact">没有找到处理任务</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>资料</th>
                <th>状态</th>
                <th>优先级</th>
                <th>步骤</th>
                <th>进度</th>
                <th>更新时间</th>
                <th>错误</th>
                <th>操作</th>
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
                        <strong className={`status-text ${active ? "pending" : job.status}`}>{stale ? "租约过期" : labelPipelineStatus(job.status)}</strong>
                        {job.cancel_requested ? <span>已请求取消</span> : null}
                        {job.locked_by ? <span>{job.locked_by}</span> : null}
                      </td>
                      <td>
                        <strong>{job.priority}</strong>
                        <span>
                          尝试 {job.attempt_count}/{job.max_attempts}
                        </span>
                      </td>
                      <td>{labelPipelineStep(job.current_step)}</td>
                      <td>
                        <span>{job.progress_percent}%</span>
                        <div className="progress-track">
                          <div style={{ width: `${job.progress_percent}%` }} />
                        </div>
                      </td>
                      <td>{formatDate(job.updated_at)}</td>
                      <td>
                        <span>{job.error_message ? `${job.last_error_code ? `${job.last_error_code}: ` : ""}${job.error_message}${job.current_step === "index" ? " · 打开设置诊断" : ""}` : "-"}</span>
                      </td>
                      <td>
                        <div className="action-group">
                          <button className="icon-button small" type="button" title="查看任务事件" onClick={() => void toggleJobEvents(job)} disabled={busyAction !== null}>
                            <Clock3 size={16} />
                          </button>
                          {job.status === "queued" ? (
                            <button className="icon-button small" type="button" title="设置优先级" onClick={() => void changeJobPriority(job)} disabled={busyAction !== null}>
                              <SlidersHorizontal size={16} />
                            </button>
                          ) : null}
                          {active ? (
                            <button className="icon-button small danger" type="button" title="取消处理任务" onClick={() => void cancelPipeline(job)} disabled={busyAction !== null}>
                              <XCircle size={16} />
                            </button>
                          ) : null}
                          {job.status === "failed" || job.status === "canceled" ? (
                            <button className="icon-button small" type="button" title="重试处理任务" onClick={() => void retryPipeline(job)} disabled={busyAction !== null}>
                              <RotateCcw size={16} />
                            </button>
                          ) : null}
                          {job.status === "succeeded" ? (
                            <button className="icon-button small" type="button" title="重新处理资料" onClick={() => void reprocessPipelineById(job.document_id)} disabled={busyAction !== null}>
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
                            <span>正在加载事件</span>
                          ) : jobEvents[job.id]?.length ? (
                            <div className="pipeline-event-list">
                              {jobEvents[job.id].map((event) => (
                                <div key={event.id} className="pipeline-event-item">
                                  <strong>{labelPipelineEventType(event.event_type)}</strong>
                                  <span>{labelPipelineStep(event.step)}</span>
                                  <span>{event.message ?? "-"}</span>
                                  <time>{formatDate(event.created_at)}</time>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span>暂无事件记录</span>
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
          <strong>已上传资料</strong>
          <span>{loading ? "加载中" : formatCount(total)}</span>
        </div>
        {documents.length === 0 ? (
          <div className="empty-panel compact">{loading ? "正在加载资料" : "没有找到资料"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>大小</th>
                <th>状态</th>
                <th>解析</th>
                <th>切块</th>
                <th>索引</th>
                <th>处理流水线</th>
                <th>上传时间</th>
                <th>操作</th>
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
                      <span className={`status-pill ${document.status}`}>{labelDocumentStatus(document.status)}</span>
                    </td>
                    <td>
                      <strong className={`status-text ${parseBusy ? "pending" : parseResult?.status ?? "idle"}`}>
                        {parseBusy ? "解析中" : labelParseStatus(parseResult?.status)}
                      </strong>
                      {parseResult ? (
                        <span>
                          {parseResult.status === "parsed"
                            ? `${parseResult.char_count} 字符${parseResult.truncated ? "，已截断" : ""}`
                            : parseResult.error_message ?? "失败"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${chunkBusy ? "pending" : chunkResult?.status ?? "idle"}`}>
                        {chunkBusy ? "切块中" : labelChunkStatus(chunkResult?.status)}
                      </strong>
                      {chunkResult ? (
                        <span>
                          {chunkResult.status === "chunked"
                            ? `${chunkResult.chunk_count} 个切块${chunkResult.truncated ? "，已截断" : ""}`
                            : chunkResult.error_message ?? "失败"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${indexBusy ? "pending" : embeddingResult?.status ?? "idle"}`}>
                        {indexBusy ? "索引中" : labelEmbeddingStatus(embeddingResult?.status)}
                      </strong>
                      {embeddingResult ? (
                        <span>
                          {embeddingResult.status === "indexed"
                            ? `${embeddingResult.indexed_chunk_count} 个向量，${embeddingResult.provider}`
                            : embeddingResult.error_message ?? "失败"}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <strong className={`status-text ${pipelineBusy || pipelineActive ? "pending" : pipelineJob?.status ?? "idle"}`}>
                        {pipelineBusy ? "排队中" : labelPipelineStatus(pipelineJob?.status)}
                      </strong>
                      {pipelineJob ? (
                        <>
                          <span>
                            {pipelineJob.status === "running" && pipelineJob.current_step
                              ? `${labelPipelineStep(pipelineJob.current_step)} · ${pipelineJob.progress_percent}%`
                              : pipelineJob.status === "failed"
                                ? `${pipelineJob.error_message ?? "失败"}${pipelineJob.current_step === "index" ? " · 打开设置诊断" : ""}`
                                : pipelineJob.status === "canceled"
                                  ? "已取消"
                                  : pipelineJob.status === "succeeded"
                                    ? "完成 · 100%"
                                    : `等待中 · ${pipelineJob.progress_percent}%`}
                          </span>
                          <div className="progress-track" aria-label={`处理进度 ${pipelineJob.progress_percent}%`}>
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
                            title={pipelineJob.status === "queued" ? "取消排队中的处理任务" : "请求当前步骤结束后取消"}
                            onClick={() => void cancelPipeline(pipelineJob)}
                            disabled={busyAction !== null}
                          >
                            <XCircle size={16} />
                          </button>
                        ) : pipelineJob?.status === "failed" || pipelineJob?.status === "canceled" ? (
                          <button
                            className="icon-button small"
                            type="button"
                            title="重试处理任务"
                            onClick={() => void retryPipeline(pipelineJob)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <RotateCcw size={16} />
                          </button>
                        ) : pipelineJob?.status === "succeeded" ? (
                          <button
                            className="icon-button small"
                            type="button"
                            title="重新处理资料"
                            onClick={() => void reprocessPipeline(document)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <ListChecks size={16} />
                          </button>
                        ) : (
                          <button
                            className="icon-button small"
                            type="button"
                            title={document.status === "archived" ? "已归档资料不能处理" : "处理资料"}
                            onClick={() => void runPipeline(document)}
                            disabled={busyAction !== null || document.status === "archived"}
                          >
                            <PlayCircle size={16} />
                          </button>
                        )}
                        <button
                          className="icon-button small"
                          type="button"
                          title={document.status === "archived" ? "已归档资料不能解析" : "解析资料"}
                          onClick={() => void runParse(document)}
                          disabled={busyAction !== null || document.status === "archived"}
                        >
                          <FileText size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canChunk ? "切块资料" : "请先解析已上传资料再切块"}
                          onClick={() => void runChunk(document)}
                          disabled={busyAction !== null || !canChunk}
                        >
                          <Scissors size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canIndex ? "索引资料" : "请先切块已解析资料再索引"}
                          onClick={() => void runIndex(document)}
                          disabled={busyAction !== null || !canIndex}
                        >
                          <Database size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={canSuggest ? "从这份资料生成待审核记忆建议" : "请先解析已上传资料再生成建议"}
                          onClick={() => void suggestFromDocument(document)}
                          disabled={busyAction !== null || !canSuggest}
                        >
                          <Lightbulb size={16} />
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={document.status === "archived" ? "恢复资料" : "归档资料"}
                          onClick={() => void changeStatus(document)}
                          disabled={busyAction !== null}
                        >
                          {document.status === "archived" ? <RotateCcw size={16} /> : <Archive size={16} />}
                        </button>
                        <button
                          className="icon-button small danger"
                          type="button"
                          title="永久删除资料"
                          onClick={() => void removeDocument(document)}
                          disabled={busyAction !== null}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                      {pipelineBusy || pipelineCancelBusy || pipelineRetryBusy || pipelineReprocessBusy || parseBusy || chunkBusy || indexBusy || suggestBusy || statusBusy || deleteBusy ? (
                        <span>
                          {pipelineBusy
                            ? "排队中"
                            : pipelineCancelBusy
                              ? "取消中"
                              : pipelineRetryBusy
                                ? "重试中"
                                : pipelineReprocessBusy
                                  ? "重新处理中"
                                  : parseBusy
                                    ? "解析中"
                                    : chunkBusy
                                      ? "切块中"
                                      : indexBusy
                                        ? "索引中"
                                        : suggestBusy
                                          ? "生成建议中"
                                          : statusBusy
                                            ? "更新中"
                                            : "删除中"}
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
            上一页
          </button>
          <span>
            第 {page} / {totalPages} 页
          </span>
          <button
            className="secondary-button"
            type="button"
            disabled={offset + PAGE_SIZE >= total || busyAction !== null || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}
