// src/useSSE.ts - SSE streaming utility. DO NOT MODIFY THIS FILE.
export async function streamSSE(
  url: string,
  body: object,
  onChunk: (data: any) => void,
  onError?: (error: Error) => void,
  headers?: Record<string, string>
): Promise<void> {
  console.log('[STREAM_START] Initiating request');

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    credentials: 'include'
  });

  if (!response.ok) {
    const text = await response.text();
    const error = new Error(`Stream failed ${response.status}: ${text.slice(0, 100)}`);
    console.error('[STREAM_ERROR]', error.message);
    onError?.(error);
    throw error;
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No reader available');

  const decoder = new TextDecoder();
  let buffer = '';

  console.log('[STREAM_OPEN] Connected');

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      // CRITICAL: Process remaining buffer before exiting
      processBuffer(buffer, onChunk, true);
      console.log('[STREAM_DONE]');
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    buffer = processBuffer(buffer, onChunk, false);
  }
}

function processBuffer(buffer: string, onChunk: (data: any) => void, isFinal: boolean): string {
  let boundary = buffer.indexOf('\n\n');

  while (boundary !== -1) {
    const message = buffer.slice(0, boundary);
    buffer = buffer.slice(boundary + 2);
    parseSSEMessage(message, onChunk);
    boundary = buffer.indexOf('\n\n');
  }

  // On final read, process any remaining data
  if (isFinal && buffer.trim()) {
    parseSSEMessage(buffer, onChunk);
    return '';
  }

  return buffer;
}

function parseSSEMessage(message: string, onChunk: (data: any) => void): void {
  for (const line of message.split('\n')) {
    if (line.startsWith('data: ')) {
      try {
        const data = JSON.parse(line.slice(6));
        console.log('[STREAM_CHUNK]', JSON.stringify(data).slice(0, 100));
        onChunk(data);
      } catch (e) {
        console.error('[STREAM_PARSE_ERROR]', line.slice(0, 50));
      }
    }
  }
}
