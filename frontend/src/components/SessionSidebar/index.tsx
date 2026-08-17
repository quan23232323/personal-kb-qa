import { Button, List, Typography } from 'antd';
import { MessageOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ChatSession } from '../../types';

interface Props {
  sessions: ChatSession[];
  activeId?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function SessionSidebar({ sessions, activeId, onSelect, onNew }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Button block icon={<PlusOutlined />} onClick={onNew} style={{ marginBottom: 12 }}>
        新对话
      </Button>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <List
          size="small"
          dataSource={sessions}
          locale={{ emptyText: '暂无会话' }}
          renderItem={(s) => (
            <List.Item
              onClick={() => onSelect(s.id)}
              style={{
                cursor: 'pointer',
                background: s.id === activeId ? '#e6f4ff' : 'transparent',
                borderRadius: 6,
                padding: '8px 12px',
                marginBottom: 4,
              }}
            >
              <List.Item.Meta
                avatar={<MessageOutlined style={{ color: '#1677ff' }} />}
                title={
                  <Typography.Text ellipsis style={{ fontSize: 13 }}>
                    {s.title || '新会话'}
                  </Typography.Text>
                }
                description={
                  <span style={{ fontSize: 12, color: '#999' }}>
                    {dayjs(s.updated_at).format('MM-DD HH:mm')}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}
