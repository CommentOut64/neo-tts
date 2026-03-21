import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30_000,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const detail = error.response.data?.detail
      throw new Error(detail || `HTTP ${error.response.status}`)
    }
    if (error.code === 'ECONNABORTED') {
      throw new Error('请求超时，请检查后端是否正常运行')
    }
    throw new Error('网络错误，请检查连接')
  },
)

export default http
