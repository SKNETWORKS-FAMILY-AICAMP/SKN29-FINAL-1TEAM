import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useRole } from '../../context/RoleContext'
import { useAuth } from '../../context/AuthContext'
import { ROLE_LABEL, type Role } from '../../types/domain'
import { Sidebar } from './Sidebar'
import { NotificationPanel } from './NotificationPanel'
import { notifications as initialNotifications, type AppNotification } from '../../data/mock'

const ROLES: Role[] = ['EMPLOYEE', 'TEAM_LEAD', 'ACCOUNTANT', 'EXECUTIVE']

export function AppLayout() {
  const { role, setRole } = useRole()
  const { user } = useAuth()
  const [notifOpen, setNotifOpen] = useState(false)
  const [notifications, setNotifications] = useState<AppNotification[]>(initialNotifications)
  const hasUnread = notifications.some((n) => n.unread)

  const markAllRead = () => setNotifications((prev) => prev.map((n) => ({ ...n, unread: false })))
  const markOneRead = (id: string) => setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, unread: false } : n)))

  // 로그인 플로우(O-1/R-0) 진입 전에도 기존 5개 화면을 데모 role-switch로 볼 수 있도록,
  // 인증된 user가 없으면 현재 선택된 role로 아바타 표시를 대신한다.
  const displayName = user?.name ?? ROLE_LABEL[role]
  const displayMeta = user ? `${user.position} · ${user.dept}` : '데모 모드'

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-area">
        <header className="topbar">
          <select
            className="text-meta"
            style={{ border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-control)', padding: '4px 8px' }}
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            aria-label="데모 역할 전환"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
          <div style={{ position: 'relative' }}>
            <button className="notif-btn" aria-label="알림" onClick={() => setNotifOpen((v) => !v)}>
              <Bell size={18} />
              {hasUnread && <span className="dot" />}
            </button>
            {notifOpen && (
              <NotificationPanel
                notifications={notifications}
                onClose={() => setNotifOpen(false)}
                onMarkAllRead={markAllRead}
                onMarkOneRead={markOneRead}
              />
            )}
          </div>
          <div className="user-chip">
            <div className="avatar">{displayName.slice(0, 1)}</div>
            <div className="who">
              <div className="name">{displayName}</div>
              <div className="meta">{displayMeta}</div>
            </div>
          </div>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
