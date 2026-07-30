import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Capability, Role } from '../types/domain'
import { ROLE_LABEL } from '../types/domain'
import { USE_MOCK } from '../api/config'
import { fetchMe, sessionLogin, sessionLogout, type MeResponse } from '../api/auth'

// 인증 상태.
//  - mock 모드: 역할 선택(R-0) → login(userObj) (localStorage 유지)
//  - 실 모드(USE_MOCK=false): Django 세션 로그인 — loginWithCredentials + 마운트 시 /api/me 복원
export interface AuthUser {
  name: string
  role: Role
  dept: string
  position: string
  /** 실 모드: 서버가 준 유효 능력(역할기본 ∪ 개인부여). mock 모드는 useCapabilities가 역할 기본값을 사용. */
  capabilities?: Capability[]
}

interface AuthCtx {
  isLoggedIn: boolean
  hasOnboarded: boolean
  user: AuthUser | null
  login: (user: AuthUser) => void
  loginWithCredentials: (username: string, password: string) => Promise<void>
  completeOnboarding: () => void
  logout: () => void
}

const STORAGE_KEY = 'tiger-auth-mock'

const Ctx = createContext<AuthCtx>({
  isLoggedIn: false,
  hasOnboarded: false,
  user: null,
  login: () => {},
  loginWithCredentials: async () => {},
  completeOnboarding: () => {},
  logout: () => {},
})

function toUser(me: MeResponse): AuthUser {
  const role = (me.role as Role) ?? 'EMPLOYEE'
  return {
    name: me.username ?? '사용자', role, dept: me.dept ?? '-', position: ROLE_LABEL[role],
    capabilities: (me.capabilities ?? []) as Capability[],
  }
}

function loadInitial(): { user: AuthUser | null; hasOnboarded: boolean } {
  if (!USE_MOCK) return { user: null, hasOnboarded: false }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : { user: null, hasOnboarded: false }
  } catch {
    return { user: null, hasOnboarded: false }
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [{ user, hasOnboarded }, setState] = useState(loadInitial)

  useEffect(() => {
    if (USE_MOCK) localStorage.setItem(STORAGE_KEY, JSON.stringify({ user, hasOnboarded }))
  }, [user, hasOnboarded])

  // 실 모드: 마운트 시 세션 복원
  useEffect(() => {
    if (USE_MOCK) return
    fetchMe()
      .then((me) => { if (me.isAuthenticated) setState({ user: toUser(me), hasOnboarded: true }) })
      .catch(() => undefined)
  }, [])

  const login = (u: AuthUser) => setState((s) => ({ ...s, user: u }))

  const loginWithCredentials = async (username: string, password: string) => {
    const me = await sessionLogin(username, password)
    if (!me.isAuthenticated) throw new Error('login failed')
    setState({ user: toUser(me), hasOnboarded: true }) // 실 로그인은 온보딩 스킵
  }

  const completeOnboarding = () => setState((s) => ({ ...s, hasOnboarded: true }))

  const logout = () => {
    if (!USE_MOCK) sessionLogout()
    setState({ user: null, hasOnboarded: false })
  }

  return (
    <Ctx.Provider value={{ isLoggedIn: user !== null, hasOnboarded, user, login, loginWithCredentials, completeOnboarding, logout }}>
      {children}
    </Ctx.Provider>
  )
}

export const useAuth = () => useContext(Ctx)
