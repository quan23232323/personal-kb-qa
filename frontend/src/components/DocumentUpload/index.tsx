import { useState } from 'react';
import { InboxOutlined } from '@ant-design/icons';
import { Button, message, Upload } from 'antd';
import type { UploadFile, UploadProps } from 'antd';
import { uploadDocuments } from '../../api/document';

interface Props {
  kbId: string;
  onUploaded: () => void;
}

export default function DocumentUpload({ kbId, onUploaded }: Props) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploading, setUploading] = useState(false);

  const props: UploadProps = {
    multiple: true,
    fileList,
    accept: '.pdf,.txt,.md,.docx,.xlsx,.xls,.csv,.pptx',
    disabled: uploading,
    beforeUpload: () => false, // 阻止自动上传，改为手动批量提交
    onChange: ({ fileList }) => setFileList(fileList),
  };

  const handleUpload = async () => {
    const files = fileList.flatMap((f) => (f.originFileObj ? [f.originFileObj] : []));
    if (files.length === 0) {
      message.warning('请先选择文件');
      return;
    }
    setUploading(true);
    try {
      const result = await uploadDocuments(kbId, files);
      if (result.failed_count > 0) {
        const names = result.failed.map((f) => `${f.filename}（${f.error}）`).join('；');
        message.warning(
          `上传完成：成功 ${result.succeeded_count} 个，失败 ${result.failed_count} 个。失败：${names}`
        );
      } else {
        message.success(`成功上传 ${result.succeeded_count} 个文件，正在处理…`);
      }
      setFileList([]);
      onUploaded();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <Upload.Dragger {...props}>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">
          {uploading ? '上传中…' : '点击或拖拽文件到此处（支持一次选择多个）'}
        </p>
        <p className="ant-upload-hint">
          支持 PDF / TXT / Markdown / DOCX / XLSX / XLS / CSV / PPTX
        </p>
      </Upload.Dragger>
      {fileList.length > 0 && (
        <Button
          type="primary"
          block
          style={{ marginTop: 12 }}
          loading={uploading}
          onClick={handleUpload}
        >
          上传 {fileList.length} 个文件
        </Button>
      )}
    </div>
  );
}
