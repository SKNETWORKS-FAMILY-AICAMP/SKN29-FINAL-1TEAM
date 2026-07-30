// 기능 단위 권한(Capability) 소비 훅 — 화면/버튼 게이트는 role 대신 이걸 쓴다.
//  - 실 모드: 서버 /api/me가 준 유효 능력(역할기본 ∪ 개인부여)을 사용.
//  - mock 모드: 데모 역할 스위처(RoleContext)를 따르도록 역할 기본값에서 파생.
import { useAuth } from '../context/AuthContext'
import { useRole } from '../context/RoleContext'
import { USE_MOCK } from '../api/config'
import { ROLE_DEFAULT_CAPABILITIES, type Capability } from '../types/domain'

export function useCapabilities(): Set<Capability> {
  const { role } = useRole()
  const { user } = useAuth()
  const caps = USE_MOCK ? ROLE_DEFAULT_CAPABILITIES[role] : (user?.capabilities ?? [])
  return new Set(caps)
}

/** can('accounting_review') 형태로 기능 권한 보유 여부를 판정하는 헬퍼를 반환. */
export function useCan(): (cap: Capability) => boolean {
  const caps = useCapabilities()
  return (cap) => caps.has(cap)
}
