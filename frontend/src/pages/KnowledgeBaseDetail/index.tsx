import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  List,
  message,
  Popconfirm,
  Row,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  MessageOutlined,
  RedoOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getKnowledgeBase } from '../../api/knowledgeBase';
import {
  deleteDocument,
  getDocumentChunks,
  listDocuments,
  reprocessDocument,
} from '../../api/document';
import { listSessions } from '../../api/chat';
import DocumentUpload from '../../components/DocumentUpload';
import type { ChatSession, Chunk, DocumentItem, KnowledgeBase } from '../../types';

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  processing: { color: 'processing', text: '处理中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function KnowledgeBaseDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [chunkDrawer, setChunkDrawer] = useState<{
    open: boolean;
    doc: DocumentItem | null;
    chunks: Chunk[];
    loading: boolean;
  }>({ open: false, doc: null, chunks: [], loading: false });

  const load = async () => {
    setLoading(true);
    try {
      const [kbData, docData, sessionData] = await Promise.all([
        getKnowledgeBase(id),
        listDocuments(id),
        listSessions(id),
      ]);
      setKb(kbData);
      setDocs(docData);
      setSessions(sessionData);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  // 有文档处于处理中时轮询刷新状态
  const hasProcessing = docs.some((d) => d.status === 'processing');
  useEffect(() => {
    if (!hasProcessing) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [hasProcessing]);

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      message.success('删除成功');
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const handleReprocess = async (docId: string) => {
    try {
      await reprocessDocument(docId);
      message.success('已重新处理');
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const handleViewChunks = async (doc: DocumentItem) => {
    setChunkDrawer({ open: true, doc, chunks: [], loading: true });
    try {
      const data = await getDocumentChunks(doc.id);
      setChunkDrawer({ open: true, doc, chunks: data.chunks, loading: false });
    } catch (e) {
      message.error((e as Error).message);
      setChunkDrawer({ open: true, doc, chunks: [], loading: false });
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge-bases')}>
          返回
        </Button>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {kb?.name ?? '加载中…'}
        </Typography.Title>
      </Space>

      <Spin spinning={loading}>
        <Row gutter={16}>
          {/* 左侧：文档列表 */}
          <Col xs={24} lg={14}>
            <Card title="文档" styles={{ body: { padding: 16 } }}>
              <DocumentUpload kbId={id} onUploaded={load} />
              <List
                style={{ marginTop: 16 }}
                dataSource={docs}
                locale={{ emptyText: <Empty description="暂无文档，上传一个开始吧" /> }}
                renderItem={(doc) => (
                  <List.Item
                    actions={[
                      <Tooltip key="chunks" title="查看提取内容">
                        <Button
                          size="small"
                          icon={<FileSearchOutlined />}
                          disabled={doc.status !== 'completed'}
                          onClick={() => handleViewChunks(doc)}
                        />
                      </Tooltip>,
                      <Tooltip key="reprocess" title="重新处理">
                        <Button
                          size="small"
                          icon={<RedoOutlined />}
                          disabled={doc.status === 'processing'}
                          onClick={() => handleReprocess(doc.id)}
                        />
                      </Tooltip>,
                      <Popconfirm
                        key="delete"
                        title="确认删除该文档？"
                        onConfirm={() => handleDelete(doc.id)}
                      >
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      avatar={<FileTextOutlined style={{ fontSize: 22, color: '#1677ff' }} />}
                      title={
                        <Space>
                          <span>{doc.filename}</span>
                          <Tag color={STATUS_TAG[doc.status]?.color}>
                            {STATUS_TAG[doc.status]?.text ?? doc.status}
                          </Tag>
                        </Space>
                      }
                      description={
                        <span style={{ fontSize: 12, color: '#999' }}>
                          {doc.file_type.toUpperCase()} · {formatSize(doc.file_size)} ·{' '}
                          {doc.chunk_count} 分块 · {dayjs(doc.created_at).format('YYYY-MM-DD HH:mm')}
                          {doc.error_message && (
                            <Typography.Text type="danger" style={{ marginLeft: 8 }}>
                              {doc.error_message}
                            </Typography.Text>
                          )}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>

          {/* 右侧：问答入口 + 近期会话 */}
          <Col xs={24} lg={10}>
            <Card title="开始提问" styles={{ body: { padding: 16 } }}>
              <Button
                type="primary"
                block
                size="large"
                icon={<MessageOutlined />}
                onClick={() => navigate(`/knowledge-bases/${id}/chat`)}
              >
                开始提问
              </Button>
              <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                基于知识库中的文档进行智能问答，支持流式输出与引用来源。
              </Typography.Paragraph>
            </Card>

            <Card title="近期会话" style={{ marginTop: 16 }} styles={{ body: { padding: 16 } }}>
              <List
                size="small"
                dataSource={sessions}
                locale={{ emptyText: '暂无会话' }}
                renderItem={(s) => (
                  <List.Item
                    onClick={() => navigate(`/knowledge-bases/${id}/chat?session=${s.id}`)}
                    style={{ cursor: 'pointer' }}
                  >
                    <List.Item.Meta
                      title={<Typography.Text ellipsis>{s.title || '新会话'}</Typography.Text>}
                      description={
                        <span style={{ fontSize: 12, color: '#999' }}>
                          {dayjs(s.updated_at).format('MM-DD HH:mm')}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </Spin>

      <Drawer
        title={`${chunkDrawer.doc?.filename ?? ''} · ${chunkDrawer.chunks.length} 个分块`}
        width={560}
        open={chunkDrawer.open}
        onClose={() => setChunkDrawer((s) => ({ ...s, open: false }))}
      >
        <Spin spinning={chunkDrawer.loading}>
          {chunkDrawer.chunks.length === 0 && !chunkDrawer.loading ? (
            <Empty description="暂无分块内容" />
          ) : (
            chunkDrawer.chunks.map((c) => (
              <Card key={c.id} size="small" style={{ marginBottom: 12 }} title={`分块 ${c.index + 1}`}>
                <Typography.Paragraph
                  style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 13, wordBreak: 'break-word' }}
                >
                  {c.content}
                </Typography.Paragraph>
              </Card>
            ))
          )}
        </Spin>
      </Drawer>
    </div>
  );
}
