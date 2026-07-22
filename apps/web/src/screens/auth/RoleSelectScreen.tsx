// R-0 역할 선택 — 로그인 직후, 계정에 등록된 역할에 따라 온보딩으로 분기(mock).
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useRole } from '../../context/RoleContext'
import { MOCK_PROFILE, ROLE_SLUG_META, SLUG_TO_ROLE, type RoleSlug } from '../../data/onboardingSteps'

const SLUGS: RoleSlug[] = ['employee', 'accountant', 'executive']

export function RoleSelectScreen() {
  const nav = useNavigate()
  const { login } = useAuth()
  const { setRole } = useRole()

  const choose = (slug: RoleSlug) => {
    const profile = MOCK_PROFILE[slug]
    login({ name: profile.name, role: SLUG_TO_ROLE[slug], dept: profile.dept, position: profile.position })
    setRole(SLUG_TO_ROLE[slug])
    nav(`/onboarding/${slug}/1`)
  }

  return (
    <div className="role-select-wrap">
      <h1>환영합니다 👋</h1>
      <p className="lead">계정에 등록된 역할에 따라 안내가 달라집니다. 역할을 확인해주세요.</p>
      <div className="role-cards">
        {SLUGS.map((slug) => {
          const meta = ROLE_SLUG_META[slug]
          return (
            <div className="role-card" key={slug}>
              <span className="emoji">{meta.emoji}</span>
              <div className="label">{meta.label}</div>
              <div className="desc">{meta.desc}</div>
              <button
                className="btn primary"
                style={{ width: '100%', justifyContent: 'center', background: meta.color, borderColor: meta.color }}
                onClick={() => choose(slug)}
              >
                시작하기
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
