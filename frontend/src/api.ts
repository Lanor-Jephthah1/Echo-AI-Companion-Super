import { streamSSE } from "./useSSE";

function getConfig() {
  return (window as any).__APP_CONFIG__;
}

export async function rpcCall<T = any>({ func, args = {}, module }: any): Promise<T> {
  const config = getConfig();
  const resolvedModule = module || `apps.${config.appName}.backend.main`;

  const res = await fetch(config.dataEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Run-Id": config.runId || "" },
    body: JSON.stringify({ module: resolvedModule, func, args }),
    credentials: "include",
  });

  if (!res.ok) throw new Error("Request failed");
  return await res.json();
}

export async function streamCall({ func, args = {}, module, onChunk, onError }: any): Promise<void> {
  const config = getConfig();
  const resolvedModule = module || `apps.${config.appName}.backend.main`;
  const streamUrl = config.dataEndpoint.replace("/data", "/data/stream");

  await streamSSE(
    streamUrl,
    { module: resolvedModule, func, args },
    onChunk,
    onError,
    { "X-Run-Id": config.runId || "" }
  );
}
