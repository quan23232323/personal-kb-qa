import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import 'antd/dist/reset.css';
import './styles/global.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 10,
          colorBgLayout: '#f5f6fa',
        },
        components: {
          Card: { borderRadiusLG: 14 },
          Button: { borderRadius: 8 },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
