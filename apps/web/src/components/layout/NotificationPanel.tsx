// F-3 알림함 — 사이드바 알림벨 클릭 시 여는 드롭다운 패널.
// Figma 프레임에 Sidebar가 별도로 없어 팝오버(패널) 형태로 구현했다.
import { useState } from 'react'
import { AlertTriangle, Calendar, CheckCircle2, ClipboardList, Wallet } from 'lucide-react'
import type { AppNotification, NotificationKind } from '../../data/mock'
import { activateOnEnterOrSpace } from '../../lib/a11y'

const ICON: Record<NotificationKind, JSX.Element> = {
  warn: <AlertTriangle size={17} />,
  rule: <ClipboardList size={17} />,
  budget: <Wallet size={17} />,
  deadline: <Calendar size={17} />,
  success: <CheckCircle2 size={17} />,
}

// 심각도 축(좌측 강조 바 + 아이콘 색) — 도장 인주색(경고)·직인 남색(정보)처럼
// 알림 종류마다 뚜렷한 톤 하나만 쓴다. 회색 원형 아이콘 하나로 뭉뚱그리지 않는다.
const KIND_TONE: Record<NotificationKind, string> = {
  warn: 'red',
  rule: 'blue',
  budget: 'amber',
  deadline: 'gray',
  success: 'green',
}

export function NotificationPanel({
  notifications,
  onClose,
  onMarkAllRead,
  onMarkOneRead,
}: {
  notifications: AppNotification[]
  onClose: () => void
  onMarkAllRead: () => void
  onMarkOneRead: (id: string) => void
}) {
  const [tab, setTab] = useState<'all' | 'unread'>('all')
  const unreadCount = notifications.filter((n) => n.unread).length
  const list = tab === 'unread' ? notifications.filter((n) => n.unread) : notifications

  return (
    <>
      <div className="notif-backdrop" onClick={onClose} />
      <div className="notif-panel" role="dialog" aria-label="알림">
        <div className="notif-panel-head">
          <div className="notif-panel-title">
            <h3>알림</h3>
            {unreadCount > 0 && <span className="notif-count">{unreadCount}</span>}
          </div>
          <button className="notif-markall" onClick={onMarkAllRead} disabled={unreadCount === 0}>모두 읽음으로 표시</button>
        </div>
        <div className="notif-tabs">
          <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>전체</button>
          <button className={tab === 'unread' ? 'active' : ''} onClick={() => setTab('unread')}>미읽음 {unreadCount > 0 && `(${unreadCount})`}</button>
        </div>
        <div className="notif-list">
          {list.length === 0 && <div className="notif-empty">표시할 알림이 없습니다.</div>}
          {list.map((n) => (
            <div
              className={'notif-row tone-' + KIND_TONE[n.kind] + (n.unread ? ' unread' : '')}
              key={n.id}
              role="button"
              tabIndex={0}
              style={{ cursor: n.unread ? 'pointer' : 'default' }}
              onClick={() => n.unread && onMarkOneRead(n.id)}
              onKeyDown={activateOnEnterOrSpace(() => n.unread && onMarkOneRead(n.id))}
            >
              <span className="icon">{ICON[n.kind]}</span>
              <div className="notif-body">
                <div className="title-row">
                  {n.title}
                  {n.unread && <span className="unread-dot" />}
                </div>
                <div className="text-meta">{n.detail}</div>
                <div className="notif-time">{n.time}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
