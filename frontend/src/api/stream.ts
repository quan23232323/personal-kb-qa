import { fetchEventSource } from '@microsoft/fetch-event-source';
import type { Source } from '../types';

export interface StreamHandlers {
  onToken: (text: string) => void;
  onSources: (sources: Source[]) => void;
  onDone: (info: { message_id: string; session_id: string }) => void;
  onError: (msg: string) => void;
}

/** 发起流式问答，返回一个 abort 函数用于取消。 */
export function streamChat(
  kbId: string,
  question: string,
  sessionId: string | undefined,
  handlers: StreamHandlers
): () => void {
  const controller = new AbortController();

  fetchEventSource(`/api/knowledge-bases/${kbId}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
    signal: controller.signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
    },
    onmessage(ev) {
      if (!ev.data) return;
      try {
        const msg = JSON.parse(ev.data);
        switch (msg.type) {
          case 'token':
            handlers.onToken(msg.content ?? '');
            break;
          case 'sources':
            handlers.onSources(msg.content ?? []);
            break;
          case 'done':
            handlers.onDone({ message_id: msg.message_id, session_id: msg.session_id });
            break;
          case 'error':
            handlers.onError(msg.content ?? '未知错误');
            break;
        }
      } catch {
        handlers.onError('解析流式响应失败');
      }
    },
    onerror(err) {
      handlers.onError(String(err));
      throw err; // 抛出以停止默认重试
    },
  });

  return () => controller.abort();
}
