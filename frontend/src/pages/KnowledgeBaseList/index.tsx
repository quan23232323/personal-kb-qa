import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Spin,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  FileTextOutlined,
  FolderOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
} from '../../api/knowledgeBase';
import type { KnowledgeBase } from '../../types';

export default function KnowledgeBaseList() {
  const navigate = useNavigate();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setKbs(await listKnowledgeBases());
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setCreating(true);
    try {
      await createKnowledgeBase(values);
      message.success('创建成功');
      setModalOpen(false);
      form.resetFields();
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteKnowledgeBase(id);
      message.success('删除成功');
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          知识库
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          新建知识库
        </Button>
      </div>

      <Spin spinning={loading}>
        {!loading && kbs.length === 0 ? (
          <Empty description="暂无知识库，点击右上角新建" />
        ) : (
          <Row gutter={[16, 16]}>
            {kbs.map((kb) => (
              <Col key={kb.id} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                  actions={[
                    <Popconfirm
                      key="delete"
                      title="确认删除该知识库？"
                      description="知识库下所有文档、会话与向量数据将被一并删除。"
                      onConfirm={() => handleDelete(kb.id)}
                    >
                      <DeleteOutlined onClick={(e) => e.stopPropagation()} />
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    avatar={<FolderOutlined style={{ fontSize: 28, color: '#1677ff' }} />}
                    title={kb.name}
                    description={
                      <div>
                        <div style={{ minHeight: 40, color: '#888', wordBreak: 'break-word' }}>
                          {kb.description || '暂无描述'}
                        </div>
                        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                          <FileTextOutlined /> {kb.document_count} 个文档 ·{' '}
                          {dayjs(kb.created_at).format('YYYY-MM-DD HH:mm')}
                        </div>
                      </div>
                    }
                  />
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      <Modal
        title="新建知识库"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        confirmLoading={creating}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="知识库名称" maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="描述（可选）" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
