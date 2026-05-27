const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

export const backendUrl = import.meta.env.VITE_BACKEND_URL ?? DEFAULT_BACKEND_URL;

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      headers: {
        Accept: "application/json",
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init.headers,
      },
      ...init,
    });
  } catch (error) {
    throw new Error(error instanceof Error && error.message === "Failed to fetch" ? "连接后端失败" : "网络请求失败");
  }

  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    try {
      const body = (await response.json()) as { detail?: { message?: string }; message?: string };
      message = body.detail?.message ?? body.message ?? message;
    } catch {
      // Keep the HTTP status message when the response body is not JSON.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: "GET" });
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: "DELETE" });
}

export async function postForm<T>(path: string, formData: FormData): Promise<T> {
  return requestJson<T>(path, { method: "POST", body: formData });
}
