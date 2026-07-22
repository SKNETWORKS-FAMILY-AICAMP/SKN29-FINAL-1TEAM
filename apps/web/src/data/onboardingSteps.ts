// R-0/EMP/ACC/EXE 온보딩 콘텐츠. OnboardingWizard가 이 데이터로 9개 화면을 렌더링한다.
import type { Role } from '../types/domain'

export type RoleSlug = 'employee' | 'accountant' | 'executive'

export const SLUG_TO_ROLE: Record<RoleSlug, Role> = {
  employee: 'EMPLOYEE',
  accountant: 'ACCOUNTANT',
  executive: 'EXECUTIVE',
}

/** TEAM_LEAD은 R-0에 별도 카드가 없음 — 사원 온보딩으로 합류(사이드바 역할-스위치로만 전환). */
export const ROLE_TO_SLUG: Record<Role, RoleSlug> = {
  EMPLOYEE: 'employee',
  TEAM_LEAD: 'employee',
  ACCOUNTANT: 'accountant',
  EXECUTIVE: 'executive',
}

export const ROLE_SLUG_META: Record<RoleSlug, { label: string; desc: string; color: string; bg: string; emoji: string }> = {
  employee: { label: '사원 (임직원)', desc: '지출 등록부터 제출까지 간편하게 관리하세요', color: 'var(--tone-blue)', bg: 'var(--tone-blue-bg)', emoji: '🧑‍💼' },
  accountant: { label: '회계·경리 담당자', desc: '검토 워크스페이스에서 AI 근거와 함께 판단하세요', color: 'var(--tone-purple)', bg: 'var(--tone-purple-bg)', emoji: '📋' },
  executive: { label: '임원진 (경영진)', desc: '거버넌스 대시보드로 정책을 결정하세요', color: 'var(--tone-teal)', bg: 'var(--tone-teal-bg)', emoji: '📊' },
}

/** RoleSelectScreen에서 로그인 세션에 채워넣을 mock 프로필(실제로는 SSO 클레임으로 대체). */
export const MOCK_PROFILE: Record<RoleSlug, { name: string; position: string; dept: string }> = {
  employee: { name: '홍길동', position: '사원', dept: 'AI사업본부' },
  accountant: { name: '김회계', position: '과장', dept: '재무회계팀' },
  executive: { name: '박상무', position: '상무', dept: '경영지원본부' },
}

export type OnboardingStepContent =
  | { kind: 'intro'; title: string; description: string }
  | { kind: 'list'; title: string; description: string; items: { label: string; sub: string; badge: string }[] }
  | { kind: 'stats'; title: string; description: string; stats: { label: string; value: string }[]; note?: string }
  | { kind: 'complete'; title: string; description: string; ctaLabel: string; ctaTo: string }

export const ONBOARDING_STEPS: Record<RoleSlug, OnboardingStepContent[]> = {
  employee: [
    {
      kind: 'intro',
      title: '초안 작성 Agent가 도와드려요',
      description: '영수증만 올리면 가맹점·금액·일시를 자동 인식하고 분류까지 제안합니다. 확인만 하면 제출 끝!',
    },
    {
      kind: 'list',
      title: '내 법인카드 연동 확인',
      description: '경영지원본부에서 등록한 카드가 자동으로 연동되었습니다.',
      items: [
        { label: '개인 배정 카드', sub: '신한카드 ****-1234', badge: '연동됨' },
        { label: '팀 카드(공용)', sub: '국민카드 ****-5678', badge: '연동됨' },
      ],
    },
    {
      kind: 'complete',
      title: '모든 준비가 끝났습니다',
      description: '{name}님 ({position}·{dept}) 계정이 준비되었습니다.\n이제 내 지출을 확인해보세요.',
      ctaLabel: '내 지출로 이동',
      ctaTo: '/my-expenses',
    },
  ],
  accountant: [
    {
      kind: 'intro',
      title: 'Risk Review Agent가 근거를 함께 드려요',
      description: '이상탐지 점수와 RAG 내규 근거를 함께 제시합니다. 최종 승인·반려는 담당자님이 결정합니다.',
    },
    {
      kind: 'list',
      title: '알림 설정 확인',
      description: '아래 알림은 기본으로 켜져 있습니다. 검토 워크스페이스에서 언제든 변경할 수 있습니다.',
      items: [
        { label: '보완요청 도착', sub: '보완 증빙이 재제출되면 즉시 알림', badge: 'ON' },
        { label: 'Rule 승인 필요', sub: '시뮬레이션 통과한 Rule 초안 대기', badge: 'ON' },
        { label: '예산 소진 경고', sub: '본부별 예산 소진율 임계치 초과', badge: 'ON' },
      ],
    },
    {
      kind: 'complete',
      title: '모든 준비가 끝났습니다',
      description: '{name}님 ({position}·{dept}) 계정이 준비되었습니다.\n이제 검토 워크스페이스를 확인해보세요.',
      ctaLabel: '검토 워크스페이스로 이동',
      ctaTo: '/review',
    },
  ],
  executive: [
    {
      kind: 'intro',
      title: '3개의 AI Agent가 정산 흐름을 자동화합니다',
      description: '초안 작성부터 규정 검토, 위험 탐지까지 — 정산 흐름의 80% 이상을 자동으로 처리하고, 사람은 애매한 건만 확인합니다.',
    },
    {
      kind: 'stats',
      title: '지금 우리 회사 현황',
      description: '로그인과 동시에 아래 지표가 실시간으로 갱신됩니다.',
      stats: [
        { label: '이번 분기 지출', value: '8.4억원' },
        { label: '자동처리율', value: '82%' },
        { label: '정책위반 의심', value: '3건' },
      ],
      note: '오늘 확인할 정책 인사이트가 2건 있어요 — 대시보드에서 바로 검토할 수 있습니다.',
    },
    {
      kind: 'complete',
      title: '모든 준비가 끝났습니다',
      description: '{name}님 ({position}·{dept}) 계정이 준비되었습니다.\n이제 거버넌스 대시보드를 확인해보세요.',
      ctaLabel: '거버넌스 대시보드로 이동',
      ctaTo: '/governance',
    },
  ],
}
