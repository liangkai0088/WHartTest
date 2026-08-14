/**
 * 执行看板 WebSocket 服务
 * 基于 ui-automation/services/websocket.ts 模式，适配事件驱动协议
 */

import { ref, shallowRef } from 'vue'
import type { WsEnvelope } from '../types'

type EventHandler = (data: Record<string, unknown>, envelope: WsEnvelope) => void
type ConnectionHandler = () => void

class ExecutionDashboardSocket {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectDelay = 2000
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private projectId: number | null = null

  private eventHandlers: Map<string, EventHandler[]> = new Map()
  private connectHandlers: ConnectionHandler[] = []
  private disconnectHandlers: ConnectionHandler[] = []
  private reconnectHandlers: ConnectionHandler[] = []

  public connected = ref(false)
  public error = shallowRef<Error | null>(null)

  /** 构建 WebSocket URL */
  private getWsUrl(projectId: number): string {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = import.meta.env.VITE_WS_HOST || window.location.host
    const url = new URL(`${protocol}//${host}/ws/execution/dashboard/`)
    url.searchParams.set('project_id', String(projectId))
    return url.toString()
  }

  /** 连接 WebSocket */
  connect(projectId: number): Promise<void> {
    this.projectId = projectId

    return new Promise((resolve, reject) => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        resolve()
        return
      }

      // 关闭旧连接
      if (this.ws) {
        this.ws.onclose = null
        this.ws.close()
      }

      const url = this.getWsUrl(projectId)
      console.log('[ExecDashWS] Connecting to:', url)

      this.ws = new WebSocket(url)

      this.ws.onopen = () => {
        console.log('[ExecDashWS] Connected')
        this.connected.value = true
        this.error.value = null
        this.reconnectAttempts = 0
        this.connectHandlers.forEach(h => h())
        resolve()
      }

      this.ws.onclose = (event) => {
        console.log('[ExecDashWS] Disconnected:', event.code, event.reason)
        this.connected.value = false
        this.disconnectHandlers.forEach(h => h())
        this.attemptReconnect()
      }

      this.ws.onerror = (event) => {
        console.error('[ExecDashWS] Error:', event)
        this.error.value = new Error('WebSocket connection error')
        reject(this.error.value)
      }

      this.ws.onmessage = (event) => {
        this.handleMessage(event.data)
      }
    })
  }

  /** 处理收到的消息 */
  private handleMessage(rawData: string) {
    try {
      const envelope: WsEnvelope = JSON.parse(rawData)
      const eventType = envelope.event

      if (!eventType) return

      console.log('[ExecDashWS] Event:', eventType, envelope.data)

      // 触发特定事件处理函数
      const handlers = this.eventHandlers.get(eventType) || []
      handlers.forEach(handler => handler(envelope.data, envelope))

      // 触发通配处理函数
      const allHandlers = this.eventHandlers.get('*') || []
      allHandlers.forEach(handler => handler(envelope.data, envelope))
    } catch (e) {
      console.error('[ExecDashWS] Failed to parse message:', e)
    }
  }

  /** 指数退避重连 */
  private attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[ExecDashWS] Max reconnect attempts reached')
      return
    }

    if (this.reconnectTimer) return

    this.reconnectAttempts++
    const delay = Math.min(this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1), 30000)
    console.log(`[ExecDashWS] Reconnecting in ${delay}ms... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null
      if (this.projectId) {
        try {
          await this.connect(this.projectId)
          // 重连成功后通知订阅者（用于触发快照重新拉取）
          this.reconnectHandlers.forEach(h => h())
        } catch {
          // connect 内部会再次触发 onclose → attemptReconnect
        }
      }
    }, delay)
  }

  /** 注册事件处理函数 */
  on(eventType: string, handler: EventHandler) {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, [])
    }
    this.eventHandlers.get(eventType)!.push(handler)
    return () => this.off(eventType, handler)
  }

  /** 移除事件处理函数 */
  off(eventType: string, handler: EventHandler) {
    const handlers = this.eventHandlers.get(eventType)
    if (handlers) {
      const idx = handlers.indexOf(handler)
      if (idx > -1) handlers.splice(idx, 1)
    }
  }

  /** 连接事件 */
  onConnect(handler: ConnectionHandler) {
    this.connectHandlers.push(handler)
    return () => {
      const idx = this.connectHandlers.indexOf(handler)
      if (idx > -1) this.connectHandlers.splice(idx, 1)
    }
  }

  /** 断开事件 */
  onDisconnect(handler: ConnectionHandler) {
    this.disconnectHandlers.push(handler)
    return () => {
      const idx = this.disconnectHandlers.indexOf(handler)
      if (idx > -1) this.disconnectHandlers.splice(idx, 1)
    }
  }

  /** 重连事件 */
  onReconnect(handler: ConnectionHandler) {
    this.reconnectHandlers.push(handler)
    return () => {
      const idx = this.reconnectHandlers.indexOf(handler)
      if (idx > -1) this.reconnectHandlers.splice(idx, 1)
    }
  }

  /** 断开连接 */
  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.connected.value = false
    this.projectId = null
    this.reconnectAttempts = 0
  }
}

/** 单例实例 */
export const executionDashboardSocket = new ExecutionDashboardSocket()
