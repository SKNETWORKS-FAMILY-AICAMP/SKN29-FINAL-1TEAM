import { NavLink } from 'react-router-dom'
import { useRole } from '../../context/RoleContext'
import type { Role } from '../../types/domain'

interface MenuItem {
  to: string
  label: string
  minRank: number
}

// 화면설계서 §1 화면 목록 — 역할 계층(사원<팀장<경리담당자<임원진) 누적형 메뉴(Figma Sidebar 스터디 기준, FR-DB-01).
// 상위 역할일수록 하위 역할의 화면까지 모두 보인다. 단 "규정 문서 관리"는 아직 화면 미구현이라 제외.
const ROLE_RANK: Record<Role, number> = { EMPLOYEE: 0, TEAM_LEAD: 1, ACCOUNTANT: 2, EXECUTIVE: 3 }

const MENU: MenuItem[] = [
  { to: '/my-expenses', label: '내 지출', minRank: 0 },
  { to: '/team', label: '팀 취합', minRank: 1 },
  { to: '/review', label: '검토 워크스페이스', minRank: 2 },
  { to: '/policy-docs', label: '규정 문서 관리', minRank: 2 },
  { to: '/rules', label: 'Rule 콘솔', minRank: 2 },
  { to: '/governance', label: '거버넌스 대시보드', minRank: 3 },
]

export function Sidebar() {
  const { role } = useRole()
  const items = MENU.filter((m) => ROLE_RANK[role] >= m.minRank)

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="logo" />
        <div>
          <div className="name">TIGER</div>
          <div className="sub">정산 자동화 플랫폼</div>
        </div>
      </div>
      <nav className="sidebar-nav">
        {items.map((m) => (
          <NavLink key={m.to} to={m.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span className="dot" />
            {m.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
