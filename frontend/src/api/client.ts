import axios, { type AxiosResponse } from 'axios';

// axios 实例：baseURL 指向后端（开发环境由 Vite proxy 转发到 127.0.0.1:8000）
const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
});

// 统一解包 { code, data, message }：code !== 0 时抛错，否则返回 data
client.interceptors.response.use(
  (response: AxiosResponse) => {
    const body = response.data;
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        return Promise.reject(new Error(body.message || '请求失败'));
      }
      return body.data;
    }
    return body;
  },
  (error) => {
    const msg = error?.response?.data?.message || error?.message || '网络错误';
    return Promise.reject(new Error(msg));
  }
);

// 类型化封装：拦截器已把响应 unwrap 成 data，这里做类型断言
export const http = {
  get: <T>(url: string, config?: object): Promise<T> =>
    client.get(url, config) as unknown as Promise<T>,
  post: <T>(url: string, data?: unknown, config?: object): Promise<T> =>
    client.post(url, data, config) as unknown as Promise<T>,
  delete: <T>(url: string, config?: object): Promise<T> =>
    client.delete(url, config) as unknown as Promise<T>,
};

export default client;
