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

/**
 * E2E 테스트가 실제 개발 스택에 진짜 문서를 올려서(`tests/e2e/test_policy_doc_ingest_e2e.py`)
 * 「규정 문서 처리 실패 — E2E 테스트 규정 <해시>」 알림이 실행할 때마다 쌓인다. 테스트는
 * 문서를 지우지만 **알림은 남는다** — `Notification.target`이 `"policydoc:12"` 문자열이라
 * FK가 아니어서 연쇄 삭제가 없다.
 *
 * 여기서 거르는 건 **표시만 막는 임시 조치**다. 행은 계속 쌓이고, 근본은 둘 중 하나로
 * 고쳐야 한다: ① 문서를 지울 때 그 target의 알림도 지운다 ② E2E 업로드를 opt-in으로 뺀다.
 */
const NOISE_TITLE = 'E2E 테스트 규정'

const isNoise = (n: Notification) => n.title.includes(NOISE_TITLE)

export async function fetchNotifications(): Promise<{ results: Notification[]; unreadCount: number }> {
  if (USE_MOCK) {
    const results = mockList()
    return { results, unreadCount: results.filter((n) => n.unread).length }
  }
  const { data } = await api.get('/notifications/')
  const all: Notification[] = data.results ?? []
  const results = all.filter((n) => !isNoise(n))
  //  서버가 준 총계에서 **거른 만큼 빼야** 배지와 목록이 어긋나지 않는다("3건"인데 목록은
  //  비어 있는 상태를 만들지 않는다). 목록이 페이지네이션되면 총계가 더 클 수 있지만,
  //  그건 원래 있던 성질이고 여기서 더 나빠지지는 않는다.
  _hiddenUnread = all.filter((n) => isNoise(n) && n.unread).length
  return {
    results,
    unreadCount: Math.max(0, Number(data.unreadCount ?? 0) - _hiddenUnread),
  }
}

/**
 * 마지막 목록 조회에서 걸러진 미읽음 수. 배지는 개수만 폴링하므로(목록까지 주기적으로
 * 받으면 서버만 친다 — `lib/notifications.ts`) 여기서 빼 주지 않으면 **배지 3 / 목록 0**이
 * 된다. 패널을 한 번도 안 연 첫 로드에서는 0이라 배지가 잠깐 실제보다 클 수 있다.
 */
let _hiddenUnread = 0

export async function fetchUnreadCount(): Promise<number> {
  if (USE_MOCK) return mockList().filter((n) => n.unread).length
  const { data } = await api.get('/notifications/unread-count/')
  return Math.max(0, Number(data.count ?? 0) - _hiddenUnread)
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
