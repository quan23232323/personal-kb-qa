import { http } from './client';
import type { ChatMessage, ChatSession } from '../types';

export function sendChat(
  kbId: string,
  question: string,
  sessionId?: string
): Promise<ChatMessage> {
  return http.post(`/knowledge-bases/${kbId}/chat`, {
    question,
    session_id: sessionId ?? null,
  });
}

export function listSessions(kbId: string): Promise<ChatSession[]> {
  return http.get(`/knowledge-bases/${kbId}/sessions`);
}

export function listMessages(sessionId: string): Promise<ChatMessage[]> {
  return http.get(`/sessions/${sessionId}/messages`);
}
