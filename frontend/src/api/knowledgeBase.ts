import { http } from './client';
import type { KnowledgeBase } from '../types';

export function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return http.get('/knowledge-bases');
}

export function createKnowledgeBase(data: { name: string; description?: string }): Promise<KnowledgeBase> {
  return http.post('/knowledge-bases', data);
}

export function getKnowledgeBase(id: string): Promise<KnowledgeBase> {
  return http.get(`/knowledge-bases/${id}`);
}

export function deleteKnowledgeBase(id: string): Promise<{ ok: boolean }> {
  return http.delete(`/knowledge-bases/${id}`);
}
