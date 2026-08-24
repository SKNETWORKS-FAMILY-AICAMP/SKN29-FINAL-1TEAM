import { useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Bell, LogOut, Printer, Landmark, WalletMinimal, CreditCard, Shield, ClipboardCheck, ListChecks, Bot,
} from 'lucide-react'
import type { Capability } from '../../types/domain'
import { useCan } from '../../lib/capabilities'
import { useAuth } from '../../context/AuthContext'
import { useRole } from '../../context/RoleContext'
import { ROLE_LABEL, type Role } from '../../types/domain'
import { NotificationPanel } from './NotificationPanel'
import { useNotifications } from '../../lib/notifications'
import { USE_MOCK } from '../../api/config'

interface MenuItem {
  to: string
  label: string
  icon: typeof Printer
  /** 필요 기능 권한(들). 없으면 인증만으로 노출(내 지출). 배열이면 하나라도 있으면 노출. */
  capability?: Capability | Capability[]
}

// 화면설계서 §1 화면 목록 — 기능 단위(Capability) 게이트(백 §3.1a). 시안 실측(`.personal/frontend/sidebar/`,
// 역할별 펼침 상태 5종 + 접힘 1종)이 정답 — 라벨·아이콘·순서는 그 파일들 기준.
//  · 내 지출: 공통(권한 불필요)
//  · 팀 예산(팀 취합·제출, S-02, 본인 팀만): team_aggregate — 팀장 전용
//  · 예산 관리(전사 팀별 예산 조회): accounting_review 또는 governance_view — 회계·임원진 전용,
//    팀장의 "팀 예산"과는 다른 화면(`.personal/frontend/예산관리/`) — 구 거버넌스 대시보드의
//    계정과목 지출 추세·예산 산정 지표를 흡수했다(거버넌스 메뉴는 팀 결정으로 폐지)
//  · 카드 관리(S-09, 법인카드 배정·회수): accounting_review — 회계 업무 범주라 기존 검토 권한과 함께 묶는다
//    (전용 capability를 새로 만들면 백엔드 동기화가 필요해 이번 프론트 작업 범위를 벗어난다)
//  · 증빙 검토(검토 워크스페이스): accounting_review  · 규정 문서: rule_view  · RULE 콘솔: rule_view(열람)
//  · AI-LAB: ai_lab
const MENU: MenuItem[] = [
  { to: '/my-expenses', label: '지출 증빙', icon: Printer },
  { to: '/team', label: '팀 예산', icon: WalletMinimal, capability: 'team_aggregate' },
  { to: '/budget', label: '예산 관리', icon: Landmark, capability: ['accounting_review', 'governance_view'] },
  { to: '/cards', label: '카드 관리', icon: CreditCard, capability: 'accounting_review' },
  { to: '/policy-docs', label: '규정 문서', icon: Shield, capability: 'rule_view' },
  { to: '/review', label: '증빙 검토', icon: ClipboardCheck, capability: 'accounting_review' },
  { to: '/rules', label: 'RULE 콘솔', icon: ListChecks, capability: 'rule_view' },
  { to: '/ai-lab', label: 'AI-LAB', icon: Bot, capability: 'ai_lab' },
]

const ROLES: Role[] = ['EMPLOYEE', 'TEAM_LEAD', 'ACCOUNTANT', 'ACCOUNTANT_LEAD', 'EXECUTIVE']

export function Sidebar() {
  const can = useCan()
  const nav = useNavigate()
  const { user, logout } = useAuth()
  const { role, setRole } = useRole()
  const [notifOpen, setNotifOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  //  배지는 미읽음 개수만 폴링하고, 목록은 패널을 열 때 한 번 받는다.
  const { items: notifications, unreadCount, loading: notifLoading, load: loadNotifications,
          readOne, readAll } = useNotifications()
  const items = MENU.filter((m) => {
    const cap = m.capability
    if (!cap) return true
    return Array.isArray(cap) ? cap.some(can) : can(cap)
  })

  const openNotifications = () => {
    const next = !notifOpen
    setNotifOpen(next)
    if (next) void loadNotifications()   // 열 때만 받는다
  }

  /** 알림 클릭 = **읽음 + 이동**. 확인했다는 뜻이 곧 그 자리로 가는 것이다. */
  const openNotification = (id: number, link: string) => {
    void readOne(id)
    setNotifOpen(false)
    //  전체 리로드(`window.location`)를 쓰지 않는다 — 세션 복원이 매번 다시 돈다.
    if (link) nav(link)
  }

  // 로그인 플로우(O-1/R-0) 진입 전에도 기존 5개 화면을 데모 role-switch로 볼 수 있도록,
  // 인증된 user가 없으면 현재 선택된 role로 아바타 표시를 대신한다.
  const displayName = user?.name ?? ROLE_LABEL[role]
  const displayMeta = user ? user.position : '데모 모드'

  return (
    <aside
      className={'sidebar' + (expanded ? ' expanded' : '')}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      <div className="sidebar-brand">
        {expanded
          ? <img src="/full_name_logo.svg" alt="로고" className="brand-logo-full" />
          : <img src="/logo.svg" alt="로고" className="brand-logo" />}
      </div>

      <div className="sidebar-user">
        <div className="avatar">{displayName.slice(0, 1)}</div>
        <div className="name">{displayName}</div>
        <div className="meta">{displayMeta}</div>
      </div>

      {/* 알림 — 기능 메뉴가 아니라 사용자 프로필에 속한 동작이라 프로필 블록 바로 아래
          자체 줄로 뺀다(기능 메뉴 목록과는 옅은 구분선으로 분리). */}
      <div className="sidebar-notif-row">
        <button
          className={'sidebar-notif-btn' + (unreadCount > 0 ? ' has-unread' : '')}
          title="알림"
          aria-label="알림"
          onClick={openNotifications}
        >
          <span className="bell-wrap">
            <Bell size={19} />
            {unreadCount > 0 && <span className="dot" />}
          </span>
          {expanded && <span className="sidebar-label">알림</span>}
          {expanded && unreadCount > 0 && <span className="notif-count-mini">{unreadCount}</span>}
        </button>
        {notifOpen && createPortal(
          <NotificationPanel
            notifications={notifications}
            unreadCount={unreadCount}
            loading={notifLoading}
            onClose={() => setNotifOpen(false)}
            onMarkAllRead={() => void readAll()}
            onOpen={openNotification}
          />,
          document.body,
        )}
      </div>

      <nav className="sidebar-nav">
        {items.map((m) => (
          <NavLink
            key={m.to}
            to={m.to}
            title={m.label}
            aria-label={m.label}
            className={({ isActive }) => 'sidebar-icon-btn' + (isActive ? ' active' : '')}
          >
            <m.icon size={20} />
            {expanded && <span className="sidebar-label">{m.label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-spacer" />

      <button className="sidebar-logout" title="로그아웃" aria-label="로그아웃" onClick={() => { logout(); nav('/login') }}>
        <LogOut size={20} />
        {expanded && <span>Logout</span>}
      </button>

      {USE_MOCK && (
        <div className="dev-role-switch">
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="데모 역할 전환">
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </div>
      )}
    </aside>
  )
}
