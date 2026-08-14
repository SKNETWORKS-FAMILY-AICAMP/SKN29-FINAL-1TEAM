import { NavLink } from 'react-router-dom'
import type { Capability } from '../../types/domain'
import { useCan } from '../../lib/capabilities'

interface MenuItem {
  to: string
  label: string
  /** 필요 기능 권한. 없으면 인증만으로 노출(내 지출·팀 현황). */
  capability?: Capability
}

// 화면설계서 §1 화면 목록 — 기능 단위(Capability) 게이트(백 §3.1a).
//  · 내 지출·팀 현황: 공통(권한 불필요, 팀 현황의 개별건 처리 컨트롤은 team_aggregate로 별도 게이트)
//  · 검토 워크스페이스: accounting_review
//  · Rule 콘솔: rule_view(열람) — ACTIVE 전환 버튼만 rule_activate로 별도 게이트  · 거버넌스: governance_view
//  · AI-LAB(AI 기능 독립 실행): ai_lab — 프롬프트·모델 내부가 보이고 LLM 비용이 나가는 관리자 도구
//  · 규정 문서 관리(/policy-docs): rule_view — 규정은 룰의 원천이고, 적재는 임베딩 비용을 쓰면서
//    모든 판정이 인용하는 코퍼스를 바꾼다. 백엔드 `PolicyDocViewSet`도 같은 capability를 요구한다.
const MENU: MenuItem[] = [
  { to: '/my-expenses', label: '내 지출' },
  { to: '/team', label: '팀 현황' },
  { to: '/review', label: '검토 워크스페이스', capability: 'accounting_review' },
  { to: '/policy-docs', label: '규정 문서 관리', capability: 'rule_view' },
  { to: '/rules', label: 'Rule 콘솔', capability: 'rule_view' },
  { to: '/governance', label: '거버넌스 대시보드', capability: 'governance_view' },
  { to: '/ai-lab', label: 'AI-LAB (관리자)', capability: 'ai_lab' },
]

export function Sidebar() {
  const can = useCan()
  const items = MENU.filter((m) => !m.capability || can(m.capability))

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="logo" />
        <div>
          <div className="name">TIGER</div>
          <div className="sub">정산 자동화 플랫폼</div>
        </div>
      </div>
      <nav className="sidebar-nav">
        {items.map((m) => (
          <NavLink key={m.to} to={m.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span className="dot" />
            {m.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
