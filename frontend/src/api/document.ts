import { http } from './client';
import type { BatchUploadResult, DocumentChunks, DocumentItem } from '../types';

export function listDocuments(kbId: string): Promise<DocumentItem[]> {
  return http.get(`/knowledge-bases/${kbId}/documents`);
}

export function uploadDocument(kbId: string, file: File): Promise<DocumentItem> {
  const fd = new FormData();
  fd.append('file', file);
  // 不手动设置 Content-Type，交给 axios 自动生成 multipart 边界
  return http.post(`/knowledge-bases/${kbId}/documents`, fd);
}

export function uploadDocuments(kbId: string, files: File[]): Promise<BatchUploadResult> {
  const fd = new FormData();
  files.forEach((f) => fd.append('files', f));
  return http.post(`/knowledge-bases/${kbId}/documents/batch`, fd);
}

export function getDocumentChunks(docId: string): Promise<DocumentChunks> {
  return http.get(`/documents/${docId}/chunks`);
}

export function deleteDocument(docId: string): Promise<{ ok: boolean }> {
  return http.delete(`/documents/${docId}`);
}

export function reprocessDocument(docId: string): Promise<DocumentItem> {
  return http.post(`/documents/${docId}/reprocess`);
}
