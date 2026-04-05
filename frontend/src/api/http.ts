import axios from 'axios'
import { toApiRequestError } from './requestSupport'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30_000,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    throw toApiRequestError(error)
  },
)

export default http
