import axios from 'axios'
import { getRuntimeConfig } from '@/platform/runtimeConfig'
import { toApiRequestError } from './requestSupport'

const runtimeConfig = getRuntimeConfig()

// 现有 API 模块仍有大量直接使用默认 axios 的相对路径请求。
// Electron 打包后运行在 file:// 下，必须同步配置默认 axios 的后端基址。
axios.defaults.baseURL = runtimeConfig.backendOrigin
axios.defaults.timeout = 30_000

const http = axios.create({
  baseURL: runtimeConfig.backendOrigin,
  timeout: 30_000,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    throw toApiRequestError(error)
  },
)

export default http
