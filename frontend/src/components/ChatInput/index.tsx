import { useState } from 'react';
import { Button, Input } from 'antd';
import { SendOutlined, StopOutlined } from '@ant-design/icons';

interface Props {
  disabled?: boolean;
  streaming?: boolean;
  onSend: (text: string) => void;
  onStop?: () => void;
}

export default function ChatInput({ disabled, streaming, onSend, onStop }: Props) {
  const [value, setValue] = useState('');

  const send = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue('');
  };

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
      <Input.TextArea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        autoSize={{ minRows: 1, maxRows: 5 }}
        disabled={disabled}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
      />
      {streaming ? (
        <Button danger icon={<StopOutlined />} onClick={onStop}>
          停止
        </Button>
      ) : (
        <Button type="primary" icon={<SendOutlined />} onClick={send} disabled={disabled || !value.trim()}>
          发送
        </Button>
      )}
    </div>
  );
}
