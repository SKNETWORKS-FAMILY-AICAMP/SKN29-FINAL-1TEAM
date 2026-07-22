import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Role } from '../types/domain'

// Mock 인증 상태. 실제로는 백엔드 세션/JWT로 대체된다(O-1 로그인, R-0 역할선택, 온보딩 3종 화면 지원용).
export interface AuthUser {
  name: string
  role: Role
  dept: string
  position: string
}

interface AuthCtx {
  isLoggedIn: boolean
  hasOnboarded: boolean
  user: AuthUser | null
  login: (user: AuthUser) => void
  completeOnboarding: () => void
  logout: () => void
}

const STORAGE_KEY = 'tiger-auth-mock'

const Ctx = createContext<AuthCtx>({
  isLoggedIn: false,
  hasOnboarded: false,
  user: null,
  login: () => {},
  completeOnboarding: () => {},
  logout: () => {},
})

function loadInitial(): { user: AuthUser | null; hasOnboarded: boolean } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { user: null, hasOnboarded: false }
    return JSON.parse(raw)
  } catch {
    return { user: null, hasOnboarded: false }
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [{ user, hasOnboarded }, setState] = useState(loadInitial)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ user, hasOnboarded }))
  }, [user, hasOnboarded])

  const login = (u: AuthUser) => setState((s) => ({ ...s, user: u }))
  const completeOnboarding = () => setState((s) => ({ ...s, hasOnboarded: true }))
  const logout = () => setState({ user: null, hasOnboarded: false })

  return (
    <Ctx.Provider value={{ isLoggedIn: user !== null, hasOnboarded, user, login, completeOnboarding, logout }}>
      {children}
    </Ctx.Provider>
  )
}

export const useAuth = () => useContext(Ctx)
