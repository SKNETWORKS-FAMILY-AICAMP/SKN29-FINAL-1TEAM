import { NavLink } from 'react-router-dom'
import { useRole } from '../../context/RoleContext'
import type { Role } from '../../types/domain'

interface MenuItem {
  to: string
  label: string
  roles: Role[]
}

// 화면설계서 §1 화면 목록 + 역할 매핑. 역할별로 노출 메뉴가 달라진다(FR-DB-01).
const MENU: MenuItem[] = [
  { to: '/my-expenses', label: '내 지출', roles: ['EMPLOYEE'] },
  { to: '/team', label: '팀 취합', roles: ['TEAM_LEAD'] },
  { to: '/review', label: '검토 워크스페이스', roles: ['ACCOUNTANT'] },
  { to: '/rules', label: 'Rule 콘솔', roles: ['ACCOUNTANT', 'EXECUTIVE'] },
  { to: '/governance', label: '거버넌스 대시보드', roles: ['EXECUTIVE'] },
]

export function Sidebar() {
  const { role } = useRole()
  const items = MENU.filter((m) => m.roles.includes(role))

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
