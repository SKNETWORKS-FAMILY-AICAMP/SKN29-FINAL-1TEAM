import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { myExpenses as initialMyExpenses, reviewItems as initialReviewItems, teamMembers as initialTeamMembers } from '../data/mock'
import type { ReviewItem, Settlement, SettlementStatus } from '../types/domain'
import { USE_MOCK } from '../api/config'
import { fetchSettlementsData } from '../api/settlements'
import { useAuth } from './AuthContext'

// 정산 데이터를 화면 간 공유하는 store.
//  - mock 모드: data/mock.ts 로 초기화 (백엔드 불필요)
//  - 실 연동 모드(USE_MOCK=false): 마운트 시 /api/settlements/ 에서 fetch
// 상태 변경(updateStatus)은 서비스 호출 성공 후 로컬에 낙관적으로 반영한다.

interface TeamMember { name: string; items: Settlement[] }

interface SettlementsCtx {
  myExpenses: Settlement[]
  teamMembers: TeamMember[]
  reviewItems: ReviewItem[]
  loading: boolean
  updateStatus: (id: string, status: SettlementStatus) => void
  findById: (id: string) => Settlement | undefined
  addExpense: (item: Settlement) => void
  removeExpense: (id: string) => void
  refresh: () => void
}

const Ctx = createContext<SettlementsCtx | null>(null)

export function SettlementsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [myExpenses, setMyExpenses] = useState<Settlement[]>(USE_MOCK ? initialMyExpenses : [])
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>(USE_MOCK ? initialTeamMembers : [])
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>(USE_MOCK ? initialReviewItems : [])
  const [loading, setLoading] = useState(!USE_MOCK)

  const refresh = () => {
    if (USE_MOCK) return
    setLoading(true)
    fetchSettlementsData(user?.name)
      .then((d) => {
        setMyExpenses(d.myExpenses)
        setTeamMembers(d.teamMembers)
        setReviewItems(d.reviewItems)
      })
      .finally(() => setLoading(false))
  }

  // 실 연동 모드에서만 fetch (로그인 사용자 변경 시 재조회)
  useEffect(() => {
    if (!USE_MOCK) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.name])

  const updateStatus = (id: string, status: SettlementStatus) => {
    setMyExpenses((prev) => prev.map((e) => (e.id === id ? { ...e, status } : e)))
    setTeamMembers((prev) => prev.map((m) => ({ ...m, items: m.items.map((i) => (i.id === id ? { ...i, status } : i)) })))
    setReviewItems((prev) => prev.map((i) => (i.id === id ? { ...i, status } : i)))
  }

  const findById = (id: string): Settlement | undefined =>
    myExpenses.find((e) => e.id === id) ??
    teamMembers.flatMap((m) => m.items).find((i) => i.id === id) ??
    reviewItems.find((i) => i.id === id)

  const addExpense = (item: Settlement) => setMyExpenses((prev) => [item, ...prev])
  const removeExpense = (id: string) => setMyExpenses((prev) => prev.filter((e) => e.id !== id))

  return (
    <Ctx.Provider value={{ myExpenses, teamMembers, reviewItems, loading, updateStatus, findById, addExpense, removeExpense, refresh }}>
      {children}
    </Ctx.Provider>
  )
}

export function useSettlements() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSettlements must be used within SettlementsProvider')
  return ctx
}
