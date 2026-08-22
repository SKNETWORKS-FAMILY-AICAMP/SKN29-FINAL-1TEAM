// 알림 상태 — 벨 배지 + 패널 목록.
//
//  **미읽음 개수만 폴링한다.** 목록까지 주기적으로 받으면 서버만 친다
//  (`RiskReviewStatus`가 진행 중일 때만 폴링하는 것과 같은 규율). 목록은 패널을 열 때 1회.
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchNotifications, fetchUnreadCount, markAllRead, markRead, markTargetRead,
  type Notification,
} from '../api/notificationService'

/** 벨 배지 갱신 주기. 알림은 실시간일 필요가 없다 — 30초면 충분하고 서버 부담이 없다. */
const POLL_MS = 30_000

export function useNotifications() {
  const [items, setItems] = useState<Notification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const refreshCount = useCallback(async () => {
    try {
      const count = await fetchUnreadCount()
      if (alive.current) setUnreadCount(count)
    } catch {
      //  개수를 못 읽은 것으로 화면을 막지 않는다. 배지가 잠깐 낡을 뿐이다.
    }
  }, [])

  useEffect(() => {
    void refreshCount()
    const t = setInterval(() => { void refreshCount() }, POLL_MS)
    return () => clearInterval(t)
  }, [refreshCount])

  /** 패널을 열 때 1회 — 목록을 받아온다. */
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { results, unreadCount: count } = await fetchNotifications()
      if (!alive.current) return
      setItems(results)
      setUnreadCount(count)
    } catch {
      if (alive.current) setItems([])
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])

  const readOne = useCallback(async (id: number) => {
    //  낙관적 반영 — 클릭하면 곧바로 페이지가 바뀌므로 서버 응답을 기다릴 이유가 없다.
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, unread: false } : n)))
    setUnreadCount((c) => Math.max(0, c - 1))
    try { await markRead(id) } catch { void refreshCount() }
  }, [refreshCount])

  const readAll = useCallback(async () => {
    setItems((prev) => prev.map((n) => ({ ...n, unread: false })))
    setUnreadCount(0)
    try { await markAllRead() } catch { void refreshCount() }
  }, [refreshCount])

  return { items, unreadCount, loading, load, readOne, readAll }
}

/**
 * 지금 화면에 열려 있는 대상의 알림을 읽음 처리한다.
 *
 * 룰 콘솔이 그래프를 열 때 쓴다 — 화면에 있으면 결과가 눈앞에 있으므로 벨을 울릴 이유가 없다.
 * `target`이 비면 아무것도 하지 않는다.
 */
export function useReadOpenTarget(target: string | null | undefined) {
  useEffect(() => {
    if (!target) return
    void markTargetRead(target)
  }, [target])
}
