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
  { to: '/team', label: '팀 취합·제출', roles: ['TEAM_LEAD'] },
  { to: '/review', label: '검토 워크스페이스', roles: ['ACCOUNTANT'] },
  { to: '/rules', label: 'Rule 콘솔', roles: ['ACCOUNTANT', 'EXECUTIVE'] },
  { to: '/governance', label: '거버넌스 대시보드', roles: ['EXECUTIVE'] },
]

export function Gnb() {
  const { role } = useRole()
  const items = MENU.filter((m) => m.roles.includes(role))
  return (
    <nav className="gnb">
      {items.map((m) => (
        <NavLink key={m.to} to={m.to} className={({ isActive }) => (isActive ? 'active' : '')}>
          {m.label}
        </NavLink>
      ))}
    </nav>
  )
}
