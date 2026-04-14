import axios from 'axios'
import { getRuntimeConfig } from '@/platform/runtimeConfig'
import { toApiRequestError } from './requestSupport'

const http = axios.create({
  baseURL: getRuntimeConfig().backendOrigin,
  timeout: 30_000,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    throw toApiRequestError(error)
  },
)

export default http
