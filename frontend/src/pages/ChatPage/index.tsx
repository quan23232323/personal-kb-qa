import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button, Card, Col, Empty, message, Row, Space, Spin, Typography } from 'antd';
import { ArrowLeftOutlined, RobotOutlined } from '@ant-design/icons';
import { getKnowledgeBase } from '../../api/knowledgeBase';
import { listMessages, listSessions } from '../../api/chat';
import { streamChat } from '../../api/stream';
import ChatInput from '../../components/ChatInput';
import MessageBubble from '../../components/MessageBubble';
import SessionSidebar from '../../components/SessionSidebar';
import type { ChatMessage, ChatSession, KnowledgeBase, Source } from '../../types';

export default function ChatPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>(
    searchParams.get('session') ?? undefined
  );
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [streamingSources, setStreamingSources] = useState<Source[]>([]);

  const streamingTextRef = useRef('');
  const streamingSourcesRef = useRef<Source[]>([]);
  const abortRef = useRef<(() => void) | null>(null);
  const stoppedRef = useRef(false);
  const skipLoadRef = useRef(false);
  const listBottomRef = useRef<HTMLDivElement>(null);

  const loadSessions = async () => {
    try {
      setSessions(await listSessions(id));
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const loadMessages = async (sessionId: string) => {
    setLoading(true);
    try {
      setMessages(await listMessages(sessionId));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getKnowledgeBase(id).then(setKb).catch((e) => message.error((e as Error).message));
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (skipLoadRef.current) {
      skipLoadRef.current = false;
      return;
    }
    if (activeSessionId) {
      loadMessages(activeSessionId);
    } else {
      setMessages([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId]);

  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  useEffect(() => {
    listBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [streamingText, messages]);

  const abortStreaming = () => {
    stoppedRef.current = true;
    abortRef.current?.();
    streamingTextRef.current = '';
    streamingSourcesRef.current = [];
    setStreaming(false);
    setStreamingText('');
    setStreamingSources([]);
  };

  const selectSession = (sid: string) => {
    if (streaming) abortStreaming();
    setActiveSessionId(sid);
    setSearchParams({ session: sid });
  };

  const newChat = () => {
    if (streaming) abortStreaming();
    setActiveSessionId(undefined);
    setSearchParams({});
    setMessages([]);
  };

  const handleSend = (text: string) => {
    if (streaming) return;

    stoppedRef.current = false;
    // 乐观渲染用户消息
    const userMsg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: activeSessionId ?? '',
      role: 'user',
      content: text,
      sources: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setStreaming(true);
    streamingTextRef.current = '';
    streamingSourcesRef.current = [];
    setStreamingText('');
    setStreamingSources([]);

    abortRef.current = streamChat(id, text, activeSessionId, {
      onToken: (t) => {
        streamingTextRef.current += t;
        setStreamingText(streamingTextRef.current);
      },
      onSources: (s) => {
        streamingSourcesRef.current = s;
        setStreamingSources(s);
      },
      onDone: (info) => {
        const assistantMsg: ChatMessage = {
          id: info.message_id,
          session_id: info.session_id,
          role: 'assistant',
          content: streamingTextRef.current,
          sources: streamingSourcesRef.current,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        skipLoadRef.current = true; // 跳过本次 activeSessionId 变化触发的 loadMessages，避免闪烁
        setActiveSessionId(info.session_id);
        setSearchParams({ session: info.session_id });
        setStreaming(false);
        setStreamingText('');
        setStreamingSources([]);
        loadSessions();
      },
      onError: (msg) => {
        if (stoppedRef.current) {
          stoppedRef.current = false;
          return;
        }
        message.error(msg);
        setStreaming(false);
        setStreamingText('');
        setStreamingSources([]);
      },
    });
  };

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 88px)' }}>
      {/* 左侧会话栏 */}
      <Col flex="260px" style={{ height: '100%' }}>
        <Card styles={{ body: { height: '100%', padding: 12 } }} style={{ height: '100%' }}>
          <SessionSidebar
            sessions={sessions}
            activeId={activeSessionId}
            onSelect={selectSession}
            onNew={newChat}
          />
        </Card>
      </Col>

      {/* 右侧对话区 */}
      <Col flex="auto" style={{ height: '100%' }}>
        <Card
          style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
          styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column', padding: 16 } }}
          title={
            <Space>
              <Button
                type="text"
                size="small"
                icon={<ArrowLeftOutlined />}
                onClick={() => navigate(`/knowledge-bases/${id}`)}
              />
              <span>{kb?.name ?? ''}</span>
            </Space>
          }
        >
          <div style={{ flex: 1, overflow: 'auto', padding: '8px 4px' }}>
            <Spin spinning={loading}>
              {messages.length === 0 && !streaming ? (
                <Empty
                  image={
                    <RobotOutlined
                      style={{ fontSize: 64, color: '#a8c6f0', marginBottom: 8 }}
                    />
                  }
                  description={
                    <div>
                      <div style={{ fontSize: 16, color: '#333', marginBottom: 4 }}>
                        开始提问吧
                      </div>
                      <div style={{ color: '#999', fontSize: 13 }}>
                        我会基于「{kb?.name ?? '知识库'}」中的文档内容回答你的问题
                      </div>
                    </div>
                  }
                  style={{ marginTop: 80 }}
                />
              ) : (
                <>
                  {messages.map((m) => (
                    <MessageBubble key={m.id} message={m} />
                  ))}
                  {streaming && (
                    <MessageBubble
                      message={{
                        id: 'streaming',
                        session_id: activeSessionId ?? '',
                        role: 'assistant',
                        content: streamingText || '思考中…',
                        sources: streamingSources,
                        created_at: '',
                      }}
                    />
                  )}
                </>
              )}
            </Spin>
            <div ref={listBottomRef} />
          </div>
          <ChatInput disabled={streaming} streaming={streaming} onSend={handleSend} onStop={abortStreaming} />
        </Card>
      </Col>
    </Row>
  );
}
