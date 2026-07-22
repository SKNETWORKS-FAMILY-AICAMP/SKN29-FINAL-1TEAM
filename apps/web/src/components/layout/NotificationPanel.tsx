// F-3 알림함 — 사이드바 알림벨 클릭 시 여는 드롭다운 패널.
// Figma 프레임에 Sidebar가 별도로 없어 팝오버(패널) 형태로 구현했다.
import { useState } from 'react'
import { AlertTriangle, Calendar, CheckCircle2, ClipboardList, Wallet } from 'lucide-react'
import { notifications, type NotificationKind } from '../../data/mock'

const ICON: Record<NotificationKind, JSX.Element> = {
  warn: <AlertTriangle size={16} color="var(--tone-red)" />,
  rule: <ClipboardList size={16} color="var(--tone-blue)" />,
  budget: <Wallet size={16} color="var(--tone-amber)" />,
  deadline: <Calendar size={16} color="var(--muted)" />,
  success: <CheckCircle2 size={16} color="var(--tone-green)" />,
}

export function NotificationPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'all' | 'unread'>('all')
  const unreadCount = notifications.filter((n) => n.unread).length
  const list = tab === 'unread' ? notifications.filter((n) => n.unread) : notifications

  return (
    <>
      <div className="notif-backdrop" onClick={onClose} />
      <div className="notif-panel" role="dialog" aria-label="알림">
        <div className="notif-panel-head">
          <h3>알림</h3>
          <button className="btn sm" onClick={onClose}>모두 읽음으로 표시</button>
        </div>
        <div className="notif-tabs">
          <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>전체</button>
          <button className={tab === 'unread' ? 'active' : ''} onClick={() => setTab('unread')}>미읽음 ({unreadCount})</button>
        </div>
        {list.map((n) => (
          <div className="notif-row" key={n.id}>
            <span className="icon">{ICON[n.kind]}</span>
            <div>
              <div className="title-row">
                {n.title}
                {n.unread && <span className="unread-dot" />}
              </div>
              <div className="text-meta">{n.detail}</div>
              <div className="text-meta">{n.time}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
