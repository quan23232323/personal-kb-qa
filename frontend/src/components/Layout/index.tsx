import { Layout as AntLayout, Typography } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { Link, Outlet } from 'react-router-dom';

const { Header, Content } = AntLayout;

export default function Layout() {
  return (
    <AntLayout style={{ minHeight: '100vh', background: '#f5f6fa' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)',
          boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <Link to="/knowledge-bases" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <BookOutlined style={{ fontSize: 22, color: '#fff' }} />
          <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
            个人知识库问答
          </Typography.Title>
        </Link>
      </Header>
      <Content style={{ padding: 24, maxWidth: 1280, margin: '0 auto', width: '100%' }}>
        <Outlet />
      </Content>
    </AntLayout>
  );
}
