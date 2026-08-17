export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  document_count: number;
}

export type DocumentStatus = 'processing' | 'completed' | 'failed';

export interface DocumentItem {
  id: string;
  kb_id: string;
  filename: string;
  file_path: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: DocumentStatus;
  error_message: string | null;
  created_at: string;
}

export interface Chunk {
  id: string;
  index: number;
  content: string;
}

export interface DocumentChunks {
  chunk_count: number;
  chunks: Chunk[];
}

export interface BatchUploadResult {
  total: number;
  succeeded_count: number;
  failed_count: number;
  succeeded: { id: string; filename: string }[];
  failed: { filename: string; error: string }[];
}

export interface Source {
  content: string;
  document_name: string;
  /** 向量余弦相似度（0~1）；仅关键词命中时为 null */
  similarity: number | null;
  /** 命中方式：语义 | 关键词 | 语义+关键词 */
  matched_by?: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: Source[];
  created_at: string;
}

export interface ChatSession {
  id: string;
  kb_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
