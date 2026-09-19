import { Layout as AntLayout, Typography } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { Link, Outlet } from 'react-router-dom';

const { Header, Content } = AntLayout;

export default function Layout() {
  return (
    // 固定视口高度、内部滚动：避免内容把整个文档撑高后产生外层滚动条
    // （会话列表变长时页面会整体滚动，短屏笔记本上主区域会被顶出视口）
    <AntLayout
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: '#f5f6fa',
      }}
    >
      <Header
        style={{
          flex: 'none',
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
      <Content
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          padding: 24,
          maxWidth: 1280,
          margin: '0 auto',
          width: '100%',
        }}
      >
        <Outlet />
      </Content>
    </AntLayout>
  );
}
