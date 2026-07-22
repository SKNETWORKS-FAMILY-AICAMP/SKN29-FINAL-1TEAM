import { createContext, useContext, useState, type ReactNode } from 'react'
import type { Role } from '../types/domain'

// 데모용 역할 전환 컨텍스트. 실제로는 JWT 클레임의 role로 대체된다.
// 역할별 GNB 노출이 달라진다(FR-DB-01).
interface RoleCtx {
  role: Role
  setRole: (r: Role) => void
}

const Ctx = createContext<RoleCtx>({ role: 'EMPLOYEE', setRole: () => {} })

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>('EMPLOYEE')
  return <Ctx.Provider value={{ role, setRole }}>{children}</Ctx.Provider>
}

export const useRole = () => useContext(Ctx)
