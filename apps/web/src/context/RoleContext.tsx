import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Role } from '../types/domain'
import { useAuth } from './AuthContext'

// 화면 접근/메뉴의 "활성 역할" 소스.
// 로그인 사용자가 있으면 그 역할로 동기화(실 세션·mock 공통). 상단 데모 스위처로 override 가능.
interface RoleCtx {
  role: Role
  setRole: (r: Role) => void
}

const Ctx = createContext<RoleCtx>({ role: 'EMPLOYEE', setRole: () => {} })

export function RoleProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [role, setRole] = useState<Role>('EMPLOYEE')

  // 로그인 사용자의 역할을 활성 역할로 반영
  useEffect(() => {
    if (user?.role) setRole(user.role)
  }, [user?.role])

  return <Ctx.Provider value={{ role, setRole }}>{children}</Ctx.Provider>
}

export const useRole = () => useContext(Ctx)
