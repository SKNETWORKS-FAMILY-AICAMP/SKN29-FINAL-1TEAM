import { createContext, useContext, useState, type ReactNode } from 'react'
import { myExpenses as initialMyExpenses, reviewItems as initialReviewItems, teamMembers as initialTeamMembers } from '../data/mock'
import type { ReviewItem, Settlement, SettlementStatus } from '../types/domain'

// 정산 데이터를 화면 간 공유하는 store. 라우트를 넘나들어도(예: 승인 → /erp/:id 이동 → 복귀)
// 상태 변경이 유지되도록 하기 위함 — 화면별 로컬 useState는 언마운트 시 초기화되어버린다.
// id 3종(S-1xxx/S-2xxx/S-3xxx)은 mock 데이터상 서로 겹치지 않아 updateStatus 하나로 전부 처리 가능.

interface TeamMember { name: string; items: Settlement[] }

interface SettlementsCtx {
  myExpenses: Settlement[]
  teamMembers: TeamMember[]
  reviewItems: ReviewItem[]
  /** 세 컬렉션을 모두 뒤져 id가 일치하는 건의 상태를 갱신한다. */
  updateStatus: (id: string, status: SettlementStatus) => void
  findById: (id: string) => Settlement | undefined
  /** F-1 신규 지출 등록 — 내 지출 목록에 새 건을 추가한다. */
  addExpense: (item: Settlement) => void
}

const Ctx = createContext<SettlementsCtx | null>(null)

export function SettlementsProvider({ children }: { children: ReactNode }) {
  const [myExpenses, setMyExpenses] = useState<Settlement[]>(initialMyExpenses)
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>(initialTeamMembers)
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>(initialReviewItems)

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

  return (
    <Ctx.Provider value={{ myExpenses, teamMembers, reviewItems, updateStatus, findById, addExpense }}>
      {children}
    </Ctx.Provider>
  )
}

export function useSettlements() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSettlements must be used within SettlementsProvider')
  return ctx
}
