export function yesNo(value: boolean) {
  return value ? "是" : "否";
}

export function onOff(value: boolean) {
  return value ? "开启" : "关闭";
}

export function formatCount(total: number, unit = "项") {
  return `共 ${total} ${unit}`;
}

export function labelDocumentStatus(status: string) {
  const labels: Record<string, string> = {
    uploaded: "已上传",
    archived: "已归档",
  };
  return labels[status] ?? status;
}

export function labelParseStatus(status: string | null | undefined) {
  const labels: Record<string, string> = {
    parsed: "已解析",
    failed: "解析失败",
    idle: "未解析",
  };
  return status ? labels[status] ?? status : "未解析";
}

export function labelChunkStatus(status: string | null | undefined) {
  const labels: Record<string, string> = {
    chunked: "已切块",
    failed: "切块失败",
    idle: "未切块",
  };
  return status ? labels[status] ?? status : "未切块";
}

export function labelEmbeddingStatus(status: string | null | undefined) {
  const labels: Record<string, string> = {
    indexed: "已索引",
    failed: "索引失败",
    idle: "未索引",
  };
  return status ? labels[status] ?? status : "未索引";
}

export function labelPipelineStatus(status: string | null | undefined) {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败",
    canceled: "已取消",
    idle: "未排队",
  };
  return status ? labels[status] ?? status : "未排队";
}

export function labelPipelineStep(step: string | null | undefined) {
  const labels: Record<string, string> = {
    parse: "解析",
    chunk: "切块",
    index: "索引",
  };
  return step ? labels[step] ?? step : "-";
}

export function labelMemoryType(type: string) {
  const labels: Record<string, string> = {
    note: "笔记",
    requirement: "需求",
    decision: "决策",
    rule: "规则",
  };
  return labels[type] ?? type;
}

export function labelMemoryStatus(status: string) {
  const labels: Record<string, string> = {
    active: "启用",
    archived: "已归档",
    all: "全部",
  };
  return labels[status] ?? status;
}

export function labelSuggestionStatus(status: string) {
  const labels: Record<string, string> = {
    pending: "待审核",
    accepted: "已接受",
    rejected: "已拒绝",
  };
  return labels[status] ?? status;
}

export function labelProviderKind(kind: string) {
  const labels: Record<string, string> = {
    embedding: "Embedding",
    llm: "LLM",
  };
  return labels[kind] ?? kind;
}

export function labelSummaryStatus(status: string) {
  const labels: Record<string, string> = {
    summarized: "已生成",
    failed: "生成失败",
    missing: "未生成",
  };
  return labels[status] ?? status;
}

export function labelPipelineEventType(type: string) {
  const labels: Record<string, string> = {
    queued: "已排队",
    claimed: "已领取",
    heartbeat: "心跳",
    progress: "进度更新",
    succeeded: "已完成",
    failed: "失败",
    canceled: "已取消",
    retry: "已重试",
    cancel_requested: "请求取消",
    priority_updated: "优先级已更新",
    reset_stale: "过期任务已恢复",
  };
  return labels[type] ?? type;
}

export function labelEnvironment(environment: string) {
  const labels: Record<string, string> = {
    development: "开发",
    production: "生产",
    test: "测试",
  };
  return labels[environment] ?? environment;
}
