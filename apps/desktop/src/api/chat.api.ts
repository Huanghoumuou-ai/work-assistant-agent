import { backendUrl, getJson, postJson } from "./client";
import type { ApiResponse, ChatResponse, ConversationItem, ConversationList, ConversationMessages, ConversationSummary } from "../types/api";

export interface ChatPayload {
  conversation_id?: string | null;
  query: string;
  top_k?: number;
  project_id?: string | null;
  document_id?: string | null;
  include_memory?: boolean;
  memory_limit?: number;
  auto_summary?: boolean;
}

export function postChat(payload: ChatPayload) {
  return postJson<ApiResponse<ChatResponse>>("/api/chat", payload);
}

export type ChatStreamEvent =
  | {
      event: "sources";
      data: {
        sources: ChatResponse["assistant_message"]["sources"];
        memory_sources: ChatResponse["assistant_message"]["memory_sources"];
        provider: string;
        model: string;
      };
    }
  | { event: "token"; data: { delta: string } }
  | { event: "done"; data: ChatResponse }
  | { event: "error"; data: { code?: string; message?: string } };

export async function streamChat(
  payload: ChatPayload,
  handlers: {
    onEvent: (event: ChatStreamEvent) => void;
    signal?: AbortSignal;
  },
) {
  const response = await fetch(`${backendUrl}/api/chat/stream`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: handlers.signal,
  });

  if (!response.ok || !response.body) {
    let message = `Request failed with ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: { message?: string }; message?: string };
      message = body.detail?.message ?? body.message ?? message;
    } catch {
      // Keep the HTTP status message when the response body is not JSON.
    }
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatchBlock = (block: string) => {
    const lines = block.split(/\r?\n/);
    const eventLine = lines.find((line) => line.startsWith("event:"));
    const dataLines = lines.filter((line) => line.startsWith("data:"));
    if (!eventLine || dataLines.length === 0) {
      return;
    }
    const event = eventLine.slice("event:".length).trim() as ChatStreamEvent["event"];
    const rawData = dataLines.map((line) => line.slice("data:".length).trimStart()).join("\n");
    const data = JSON.parse(rawData) as ChatStreamEvent["data"];
    handlers.onEvent({ event, data } as ChatStreamEvent);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      if (block.trim()) {
        dispatchBlock(block);
      }
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    dispatchBlock(buffer);
  }
}

export function getConversations(limit = 50, offset = 0) {
  return getJson<ApiResponse<ConversationList>>(`/api/conversations?limit=${limit}&offset=${offset}`);
}

export function getConversation(conversationId: string) {
  return getJson<ApiResponse<ConversationItem>>(`/api/conversations/${conversationId}`);
}

export function getConversationMessages(conversationId: string) {
  return getJson<ApiResponse<ConversationMessages>>(`/api/conversations/${conversationId}/messages`);
}

export function getConversationSummary(conversationId: string) {
  return getJson<ApiResponse<ConversationSummary>>(`/api/conversations/${conversationId}/summary`);
}

export function generateConversationSummary(conversationId: string) {
  return postJson<ApiResponse<ConversationSummary>>(`/api/conversations/${conversationId}/summary`, {});
}
