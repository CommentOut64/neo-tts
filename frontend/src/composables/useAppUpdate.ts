import { ref } from 'vue'
import { getVersion, checkUpdate, type UpdateCheckResult } from '@/api/system'
import { ElMessage } from 'element-plus'

export function useAppUpdate() {
  const version = ref('获取中...')
  const isCheckingUpdate = ref(false)
  const pendingUpdateInfo = ref<UpdateCheckResult | null>(null)
  
  async function fetchVersion() {
    try {
      const res = await getVersion()
      version.value = res.version
    } catch {
      version.value = '未知'
    }
  }

  async function handleCheckUpdate(silent: boolean = false) {
    if (isCheckingUpdate.value) return
    isCheckingUpdate.value = true
    try {
      const res = await checkUpdate()
      if (res.has_update) {
        pendingUpdateInfo.value = res
      } else if (!silent) {
        ElMessage.success('当前已是最新版本')
      }
    } catch (e: any) {
      if (!silent) {
        ElMessage.error('检查更新失败: ' + (e.message || '网络错误'))
      }
    } finally {
      isCheckingUpdate.value = false
    }
  }

  function ignoreUpdate() {
    pendingUpdateInfo.value = null
  }

  return {
    version,
    isCheckingUpdate,
    pendingUpdateInfo,
    fetchVersion,
    handleCheckUpdate,
    ignoreUpdate
  }
}
