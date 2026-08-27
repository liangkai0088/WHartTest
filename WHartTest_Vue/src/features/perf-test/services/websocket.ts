// 性能测试实时大盘 WebSocket 服务

import { shallowRef, ref } from 'vue'
import type { PerfRealtimeUpdate } from '../types'

type UpdateHandler = (data: PerfRealtimeUpdate) => void

class PerfWebSocketService {
  private ws: WebSocket | null = null
  private handlers: Set<UpdateHandler> = new Set()
  private executionId: number | null = null

  public connected = ref(false)
  public error = shallowRef<Error | null>(null)

  private getWsUrl(executionId: number): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_WS_HOST || window.location.host
    return `${protocol}//${host}/ws/perf-test/${executionId}/`
  }

  connect(executionId: number): Promise<void> {
    this.disconnect()
    this.executionId = executionId
    return new Promise((resolve, reject) => {
      if (!window.WebSocket) {
        this.error.value = new Error('当前浏览器不支持 WebSocket')
        reject(this.error.value)
        return
      }
      this.ws = new WebSocket(this.getWsUrl(executionId))
      this.ws.onopen = () => {
        this.connected.value = true
        this.error.value = null
        resolve()
      }
      this.ws.onerror = (err) => {
        this.error.value = err as unknown as Error
      }
      this.ws.onclose = () => {
        this.connected.value = false
      }
      this.ws.onmessage = (event) => {
        this.handleMessage(event.data as string)
      }
    })
  }

  private handleMessage(raw: string) {
    try {
      const parsed = JSON.parse(raw)
      const data = parsed?.data ?? parsed
      const payload: PerfRealtimeUpdate = {
        progress: Number(data.progress ?? 0),
        rps: Number(data.rps ?? 0),
        users: Number(data.users ?? 0),
      }
      this.handlers.forEach((handler) => handler(payload))
    } catch {
      // 忽略无法解析的帧，保持连接稳定
    }
  }

  onUpdate(handler: UpdateHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  disconnect() {
    this.handlers.clear()
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.connected.value = false
  }
}

export const perfWebSocket = new PerfWebSocketService()
