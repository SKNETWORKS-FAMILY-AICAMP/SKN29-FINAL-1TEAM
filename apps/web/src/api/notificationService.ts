// 알림 API — **메시지 + 이동할 페이지**.
//
//  `link`는 서버가 완성해 보낸다(`/review` 같은 상대 경로). 화면이 「이 종류면 이 경로」를
//  들고 있으면 곧 서버와 갈린다 — 플래그 라벨을 프론트가 복사했다가 어긋났던 자리와 같다.
//  지금은 **페이지 이동까지만** 한다(특정 건 열기·하이라이트는 다음 단계).
import { api } from './client'
import { USE_MOCK } from './config'
import { notifications as mockRows } from '../data/mock'

export interface Notification {
  id: number
  kind: string
  kindLabel: string
  title: string
  body: string
  /** 클릭 시 이동할 상대 경로. 서버가 정한다. */
  link: string
  /** `"rulegraph:12"` 형태. 화면이 열려 있는 대상을 자동 읽음 처리할 때 쓴다. */
  target: string
  /** 묶인 알림의 건수 — **마지막으로 읽은 뒤 몇 건이 쌓였나**(현재 대기 총량이 아니다). */
  count: number
  unread: boolean
  createdAt: string
  updatedAt: string
  actorName: string
}

/** mock 모드 폴백 — 백엔드 없이 화면을 볼 때만 쓴다. */
function mockList(): Notification[] {
  return mockRows.map((n, i) => ({
    id: i + 1,
    kind: n.kind.toUpperCase(),
    kindLabel: n.kind,
    title: n.title,
    body: n.detail,
    link: '/my-expenses',
    target: '',
    count: 1,
    unread: n.unread,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    actorName: '',
  }))
}

export async function fetchNotifications(): Promise<{ results: Notification[]; unreadCount: number }> {
  if (USE_MOCK) {
    const results = mockList()
    return { results, unreadCount: results.filter((n) => n.unread).length }
  }
  const { data } = await api.get('/notifications/')
  return { results: data.results ?? [], unreadCount: data.unreadCount ?? 0 }
}

export async function fetchUnreadCount(): Promise<number> {
  if (USE_MOCK) return mockList().filter((n) => n.unread).length
  const { data } = await api.get('/notifications/unread-count/')
  return Number(data.count ?? 0)
}

export async function markRead(id: number): Promise<void> {
  if (USE_MOCK) return
  await api.post(`/notifications/${id}/read/`)
}

export async function markAllRead(): Promise<void> {
  if (USE_MOCK) return
  await api.post('/notifications/read-all/')
}

/**
 * 화면에 열려 있는 대상의 알림을 접는다.
 *
 * 「룰 수정 완료는 그래프 수정 화면을 벗어나 있을 때만 알린다」를 **서버가 판단할 수 없어서**
 * (서버는 화면이 어디 있는지 모른다) 알림은 항상 만들고 화면이 접는 구조다.
 */
export async function markTargetRead(target: string): Promise<void> {
  if (USE_MOCK || !target) return
  await api.post('/notifications/read-target/', { target })
}
