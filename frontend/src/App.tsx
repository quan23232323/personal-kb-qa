import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import KnowledgeBaseList from './pages/KnowledgeBaseList';
import KnowledgeBaseDetail from './pages/KnowledgeBaseDetail';
import ChatPage from './pages/ChatPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/knowledge-bases" replace />} />
          <Route path="/knowledge-bases" element={<KnowledgeBaseList />} />
          <Route path="/knowledge-bases/:id" element={<KnowledgeBaseDetail />} />
          <Route path="/knowledge-bases/:id/chat" element={<ChatPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
