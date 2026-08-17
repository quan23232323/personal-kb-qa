import { Avatar, Collapse, Tag, Typography } from 'antd';
import { FileTextOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, Source } from '../../types';

interface Props {
  message: ChatMessage;
}

/** 生成来源命中标签：相似度百分比 / 关键词命中 */
function sourceMeta(s: Source): string {
  if (s.similarity != null) {
    const pct = `相似度 ${(s.similarity * 100).toFixed(1)}%`;
    return s.matched_by === '语义+关键词' ? `${pct} · 关键词命中` : pct;
  }
  return '关键词命中';
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        gap: 10,
        alignItems: 'flex-start',
        marginBottom: 16,
      }}
    >
      <Avatar
        size={36}
        style={{
          background: isUser ? '#52c41a' : '#1677ff',
          flexShrink: 0,
          boxShadow: '0 1px 3px rgba(0,0,0,0.12)',
        }}
        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
      />
      <div style={{ maxWidth: '74%' }}>
        <div
          style={{
            background: isUser ? '#1677ff' : '#fff',
            color: isUser ? '#fff' : 'rgba(0,0,0,0.88)',
            padding: '10px 14px',
            borderRadius: isUser ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
            wordBreak: 'break-word',
            border: isUser ? 'none' : '1px solid #eef0f4',
            boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
          }}
        >
          {isUser ? (
            <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>
          ) : (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && message.sources.length > 0 && (
          <Collapse
            size="small"
            ghost
            style={{ marginTop: 6, background: '#fff', borderRadius: 8 }}
            items={[
              {
                key: 'sources',
                label: (
                  <span style={{ fontSize: 12, color: '#888' }}>
                    <FileTextOutlined /> 引用来源（{message.sources.length}）
                  </span>
                ),
                children: message.sources.map((s, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
                    <div style={{ fontWeight: 500, color: '#333' }}>
                      {s.document_name} · {sourceMeta(s)}
                      {s.matched_by === '关键词' && (
                        <Tag color="orange" style={{ marginLeft: 6, lineHeight: '18px' }}>
                          关键词
                        </Tag>
                      )}
                    </div>
                    <Typography.Paragraph
                      ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                      style={{ margin: '4px 0 0' }}
                    >
                      {s.content}
                    </Typography.Paragraph>
                  </div>
                )),
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
