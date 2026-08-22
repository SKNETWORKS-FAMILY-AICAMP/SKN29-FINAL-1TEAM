// F-3 알림함 — 사이드바 알림벨 클릭 시 여는 드롭다운 패널.
//
//  **알림 = 메시지 + 이동할 페이지.** 행을 누르면 읽음 처리되고 그 자리로 이동한다
//  (확인했다는 뜻이 곧 그 자리로 가는 것이다). 지금은 **페이지 이동까지만** 한다 —
//  특정 건을 열거나 하이라이트하는 건 다음 단계다.
//
//  아이콘 매핑은 화면 소관이지만 **모르는 종류도 렌더된다** — 서버가 종류를 늘렸을 때
//  화면이 깨지는 대신 기본 아이콘+회색 톤으로 떨어진다(비용분류 색상 팔레트와 같은 규율).
import { useState } from 'react'
import {
  AlertTriangle, Bell, CheckCircle2, ClipboardList, FileText, Loader2, XCircle,
} from 'lucide-react'
import type { Notification } from '../../api/notificationService'
import { activateOnEnterOrSpace } from '../../lib/a11y'

const ICON: Record<string, JSX.Element> = {
  SETTLEMENT_RETURNED: <AlertTriangle size={17} />,
  SETTLEMENT_REJECTED: <XCircle size={17} />,
  TEAM_COLLECT_PENDING: <ClipboardList size={17} />,
  REVIEW_PENDING: <ClipboardList size={17} />,
  DOC_INGEST_DONE: <FileText size={17} />,
  DOC_INGEST_FAILED: <FileText size={17} />,
  RULE_AUTO_CREATED: <CheckCircle2 size={17} />,
  RULE_UPDATED: <CheckCircle2 size={17} />,
  RULE_SIMULATION_DONE: <ClipboardList size={17} />,
  RULE_ACTIVATION_REQUESTED: <AlertTriangle size={17} />,
  RULE_ACTIVATED: <CheckCircle2 size={17} />,
}
const FALLBACK_ICON = <Bell size={17} />

// 심각도 축(좌측 강조 바 + 아이콘 색) — 도장 인주색(경고)·직인 남색(정보)처럼 알림 종류마다
// 뚜렷한 톤 하나만 쓴다. 회색 원형 아이콘 하나로 뭉뚱그리지 않는다. 값은 종류별 아이콘이 원래
// 쓰던 색(SETTLEMENT_RETURNED=amber 등)을 그대로 옮긴 것 — 의미를 새로 정의하지 않았다.
const KIND_TONE: Record<string, string> = {
  SETTLEMENT_RETURNED: 'amber',
  SETTLEMENT_REJECTED: 'red',
  TEAM_COLLECT_PENDING: 'blue',
  REVIEW_PENDING: 'blue',
  DOC_INGEST_DONE: 'green',
  DOC_INGEST_FAILED: 'red',
  RULE_AUTO_CREATED: 'green',
  RULE_UPDATED: 'green',
  RULE_SIMULATION_DONE: 'purple',
  RULE_ACTIVATION_REQUESTED: 'amber',
  RULE_ACTIVATED: 'blue',
}
const FALLBACK_TONE = 'gray'

/** 상대 시각 — 서버가 준 ISO 시각을 사람 말로. */
function ago(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const min = Math.floor((Date.now() - then) / 60000)
  if (min < 1) return '방금'
  if (min < 60) return `${min}분 전`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour}시간 전`
  const day = Math.floor(hour / 24)
  return day === 1 ? '어제' : `${day}일 전`
}

export function NotificationPanel({
  notifications, unreadCount, loading, onClose, onMarkAllRead, onOpen,
}: {
  notifications: Notification[]
  unreadCount: number
  loading?: boolean
  onClose: () => void
  onMarkAllRead: () => void
  /** 읽음 처리 + `link`로 이동. */
  onOpen: (id: number, link: string) => void
}) {
  const [tab, setTab] = useState<'all' | 'unread'>('all')
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
          {loading && (
            <div className="notif-empty row" style={{ justifyContent: 'center', gap: 8 }}>
              <Loader2 size={14} className="spin" /> 알림을 불러오는 중…
            </div>
          )}
          {!loading && list.length === 0 && <div className="notif-empty">표시할 알림이 없습니다.</div>}
          {!loading && list.map((n) => (
            <div
              className={'notif-row tone-' + (KIND_TONE[n.kind] ?? FALLBACK_TONE) + (n.unread ? ' unread' : '')}
              key={n.id}
              role="button"
              tabIndex={0}
              style={{ cursor: 'pointer' }}
              onClick={() => onOpen(n.id, n.link)}
              onKeyDown={activateOnEnterOrSpace(() => onOpen(n.id, n.link))}
            >
              <span className="icon">{ICON[n.kind] ?? FALLBACK_ICON}</span>
              <div className="notif-body">
                <div className="title-row">
                  {n.title}
                  {/*  묶인 알림의 건수 — 「마지막으로 읽은 뒤 쌓인 수」다(현재 대기 총량이 아니다). */}
                  {n.count > 1 && <span className="tag" style={{ marginLeft: 6 }}>{n.count}건</span>}
                  {n.unread && <span className="unread-dot" />}
                </div>
                {n.body && <div className="text-meta">{n.body}</div>}
                <div className="notif-time">{ago(n.updatedAt)}{n.actorName ? ` · ${n.actorName}` : ''}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
