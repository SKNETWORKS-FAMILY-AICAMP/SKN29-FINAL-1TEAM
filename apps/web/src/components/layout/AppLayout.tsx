import { Outlet } from 'react-router-dom'
import { useRole } from '../../context/RoleContext'
import { ROLE_LABEL, type Role } from '../../types/domain'
import { Gnb } from './Gnb'

const ROLES: Role[] = ['EMPLOYEE', 'TEAM_LEAD', 'ACCOUNTANT', 'EXECUTIVE']

export function AppLayout() {
  const { role, setRole } = useRole()
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          법인카드 정산 자동화<small>Tiger Inc.</small>
        </div>
        <Gnb />
        <div className="role-switch">
          <span className="muted" style={{ fontSize: 12 }}>데모 역할</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  )
}
