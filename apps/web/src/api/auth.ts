// 세션 로그인 API (JWT 대신 Django 세션 인증).
import { api } from './client'

export interface MeResponse {
  isAuthenticated: boolean
  username?: string
  role?: string
  dept?: string | null
  isSuperuser?: boolean
}

export async function fetchMe(): Promise<MeResponse> {
  return (await api.get('/me/')).data
}

export async function sessionLogin(username: string, password: string): Promise<MeResponse> {
  await api.get('/auth/csrf/').catch(() => undefined) // csrftoken 쿠키(운영 CSRF 대비)
  return (await api.post('/auth/login/', { username, password })).data
}

export async function sessionLogout(): Promise<void> {
  await api.post('/auth/logout/').catch(() => undefined)
}
