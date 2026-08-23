// S-09 법인카드 관리 서비스 — 화면은 배열을 직접 만지지 않고 이 함수들을 거친다.
//
// 서버가 계산해 내려주는 값을 화면이 다시 계산하지 않는다:
//   · usage      그 달 실제 결제 합계
//   · attention  "회수/중지가 필요한가"(퇴사·반복 이상사용) + 그 근거 문장
// 화면에서 다시 판정하면 임계값 사본이 두 벌 생기고, 곧 서로 다른 말을 한다.
import { endpoints } from './client'

export type CardType = 'PERSONAL' | 'TEAM' | 'SHARED' | 'POST_PAID' | 'PREPAID'
export type CardStatus = 'ACTIVE' | 'STOPPED'

export interface CardAttention {
  reason: 'RETIRED_OWNER' | 'REPEAT_ANOMALY'
  label: string
  note: string
  dateLabel: string
  date: string
}

export interface CorpCard {
  id: number
  name: string
  number: string
  type: CardType
  typeLabel: string
  assignee: string
  teamId: number | null
  teamName: string | null
  ownerId: number | null
  usage: number
  limit: number
  status: CardStatus
  statusLabel: string
  stoppedReason: string
  stoppedAt: string | null
  attention: CardAttention | null
}

export interface CardOption { id: number; name: string; team?: string }

export interface CardListResult {
  month: string
  cards: CorpCard[]
  teams: CardOption[]
  people: CardOption[]
}

export interface AttentionGroupData {
  reason: string
  label: string
  cards: CorpCard[]
}

export async function fetchCards(): Promise<CardListResult> {
  const { data } = await endpoints.cards()
  return {
    month: data.month,
    cards: data.cards ?? [],
    teams: data.teams ?? [],
    people: data.people ?? [],
  }
}

/**
 * 회수/중지 필요 카드 — **지금 화면은 이걸 부르지 않는다.**
 *
 * S-09의 조치 큐가 시연용 목업(`data/cardAttentionMock.ts`)으로 대체돼 있다: 실 API가 내는
 * 사유는 퇴사·반복 이상사용 둘뿐이고 분실신고·휴직·장기미사용은 그 사실을 담는 자리가
 * 도메인에 아직 없다. 엔드포인트는 그대로 살아 있으니 목업을 걷어낼 때 이 함수로 돌아온다.
 */
export async function fetchCardAttention(): Promise<{
  total: number
  groups: AttentionGroupData[]
  anomalyRule: { windowDays: number; minCount: number }
}> {
  const { data } = await endpoints.cardsAttention()
  return { total: data.total ?? 0, groups: data.groups ?? [], anomalyRule: data.anomalyRule }
}

/** 배정 변경. 팀 배정과 개인 배정은 서버에서 서로를 지운다(둘 다 채워지지 않는다). */
export async function assignCard(
  id: number,
  target: { mode: 'TEAM' | 'PERSONAL'; teamId?: number; userId?: number; reason?: string },
): Promise<CorpCard> {
  const { data } = await endpoints.assignCard(id, target)
  return data
}

/** 회수·정지. 사유는 서버에서 필수다 — 비어 있으면 400이 온다. */
export async function stopCard(id: number, reason: string): Promise<CorpCard> {
  const { data } = await endpoints.stopCard(id, reason)
  return data
}

export async function reactivateCard(id: number): Promise<CorpCard> {
  const { data } = await endpoints.reactivateCard(id)
  return data
}

/**
 * 지출 등록·수정 화면의 카드 선택지 — **본인이 쓸 수 있는 카드만.**
 *
 * 예전엔 화면이 카드 **구분**(개인/팀/공용)만 골랐고 서버가 그 구분의 아무 카드나 붙였다.
 * 카드 귀속은 판정 사실(`card.actual_user_recorded` 등)이 되므로 엉뚱한 카드가 붙으면
 * 그대로 오판이 된다.
 */
export async function fetchMyCards(): Promise<CorpCard[]> {
  const { data } = await endpoints.myCards()
  return data ?? []
}
