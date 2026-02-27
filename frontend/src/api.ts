import { streamSSE } from "./useSSE";

const CLIENT_ID_KEY = "echo_client_id_v1";

function getClientId(): string {
  try {
    const existing = localStorage.getItem(CLIENT_ID_KEY);
    if (existing) return existing;
    const generated =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `echo-${Math.random().toString(36).slice(2)}-${Date.now()}`;
    localStorage.setItem(CLIENT_ID_KEY, generated);
    return generated;
  } catch {
    return "anon";
  }
}

function endpointForFunc(func: string): string {
  const known: Record<string, string> = {
    get_threads: "/api/get_threads",
    create_thread: "/api/create_thread",
    delete_thread: "/api/delete_thread",
    summarize_thread: "/api/summarize_thread",
    create_share_link: "/api/create_share_link",
    import_shared_thread: "/api/import_shared_thread",
    transcribe_audio: "/api/transcribe_audio",
  };
  return known[func] || `/api/${func}`;
}

export async function rpcCall<T = any>({ func, args = {} }: any): Promise<T> {
  const res = await fetch(endpointForFunc(func), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...args, client_id: args?.client_id || getClientId() }),
    credentials: "include",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Request failed");
  }
  return await res.json();
}

export async function streamCall({ func, args = {}, onChunk, onError }: any): Promise<void> {
  if (func !== "chat_streaming") {
    throw new Error(`Unsupported stream function: ${func}`);
  }
  await streamSSE(
    "/api/chat_streaming",
    { ...args, client_id: args?.client_id || getClientId() },
    onChunk,
    onError
  );
}

