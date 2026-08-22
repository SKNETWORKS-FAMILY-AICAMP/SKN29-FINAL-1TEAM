// 비용분류 어휘 — **서버가 정본**(`settlements.Category` → `GET /api/meta/categories/`).
//
// 화면 곳곳에 목록 상수를 복사해 두면 반드시 갈라진다(룰 플래그 라벨이 백엔드 27개 vs
// 프론트 9개로 어긋났던 이력). 그래서 드롭다운·필터·scope 선택이 전부 이 훅 하나를 본다.
//
// 캐시는 모듈 수준 1개 + 진행 중 요청 공유 — 한 화면에 드롭다운이 여럿 있어도 요청은
// 한 번이다. 어휘는 배포 단위로만 바뀌므로 만료를 두지 않는다(새로고침이면 충분).
import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { USE_MOCK } from '../api/config'
import { CATEGORIES_FALLBACK, type Category } from '../types/domain'

export interface CategoryMeta {
  /** 저장·판정에 쓰이는 값. */
  value: Category
  /** 화면 표기. 지금은 값과 같지만 서버가 정하므로 그대로 쓴다. */
  label: string
}

export interface CategoryVocabulary {
  categories: CategoryMeta[]
  /** 룰 그래프 scope 선택용 — GLOBAL ∪ 분류. 조합 규칙도 서버가 정한다. */
  ruleScopes: string[]
}

const FALLBACK: CategoryVocabulary = {
  categories: CATEGORIES_FALLBACK.map((value) => ({ value, label: value })),
  ruleScopes: ['GLOBAL', ...CATEGORIES_FALLBACK],
}

let cached: CategoryVocabulary | null = USE_MOCK ? FALLBACK : null
let inFlight: Promise<CategoryVocabulary> | null = null

function normalize(data: unknown): CategoryVocabulary {
  const raw = (data ?? {}) as Partial<{ categories: unknown; ruleScopes: unknown }>
  const categories = Array.isArray(raw.categories)
    ? raw.categories
        .map((row) => row as Partial<CategoryMeta>)
        .filter((row): row is CategoryMeta => Boolean(row?.value))
        .map((row) => ({ value: row.value, label: row.label || row.value }))
    : []
  //  빈 목록을 캐시하면 드롭다운이 통째로 비어 아무것도 고를 수 없게 된다 — 그 경우는
  //  응답이 왔어도 실패로 다룬다(폴백이 낡은 목록일 수는 있어도 비어 있지는 않다).
  if (categories.length === 0) throw new Error('비용분류 어휘가 비어 있습니다')
  const ruleScopes = Array.isArray(raw.ruleScopes) && raw.ruleScopes.length
    ? raw.ruleScopes.map(String)
    : ['GLOBAL', ...categories.map((c) => c.value)]
  return { categories, ruleScopes }
}

export async function fetchCategoryVocabulary(): Promise<CategoryVocabulary> {
  if (cached) return cached
  if (!inFlight) {
    inFlight = api
      .get('/meta/categories/')
      .then((res) => {
        cached = normalize(res.data)
        return cached
      })
      .catch((err) => {
        //  서버를 못 읽었다고 화면을 못 쓰게 만들지 않는다. 다만 **캐시하지 않는다** —
        //  다음 마운트에서 다시 시도해야 배포 직후 잠깐의 장애가 세션 내내 남지 않는다.
        console.warn('비용분류 어휘 조회 실패 — 기본 목록으로 표시합니다', err)
        return FALLBACK
      })
      .finally(() => {
        inFlight = null
      })
  }
  return inFlight
}

/** 비용분류 어휘. 로딩 중에도 목록을 비우지 않는다(빈 드롭다운은 오류처럼 보인다). */
export function useCategories(): CategoryVocabulary & { loading: boolean } {
  const [vocab, setVocab] = useState<CategoryVocabulary>(cached ?? FALLBACK)
  const [loading, setLoading] = useState(!cached)

  useEffect(() => {
    if (cached) return
    let alive = true
    fetchCategoryVocabulary().then((next) => {
      if (!alive) return
      setVocab(next)
      setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [])

  return { ...vocab, loading }
}

/** 테스트·스토리에서 캐시를 비운다. */
export function __resetCategoryCache(): void {
  cached = USE_MOCK ? FALLBACK : null
  inFlight = null
}
