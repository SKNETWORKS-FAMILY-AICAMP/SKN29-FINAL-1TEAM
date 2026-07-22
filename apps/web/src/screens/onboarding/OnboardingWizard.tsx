// EMP/ACC/EXE 온보딩 3단계 공용 셸 — data/onboardingSteps.ts의 콘텐츠로 9개 화면을 커버한다.
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Check } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { MOCK_PROFILE, ONBOARDING_STEPS, ROLE_SLUG_META, type RoleSlug } from '../../data/onboardingSteps'

const VALID_SLUGS: RoleSlug[] = ['employee', 'accountant', 'executive']

function fillTemplate(text: string, vars: Record<string, string>) {
  return text.replace(/\{(\w+)\}/g, (_, key) => vars[key] ?? '')
}

export function OnboardingWizard() {
  const { role, step } = useParams<{ role: string; step: string }>()
  const nav = useNavigate()
  const { user, completeOnboarding } = useAuth()

  const isValidSlug = (r?: string): r is RoleSlug => VALID_SLUGS.includes(r as RoleSlug)
  if (!isValidSlug(role)) return <Navigate to="/select-role" replace />

  const steps = ONBOARDING_STEPS[role]
  const stepIndex = Number(step) - 1
  if (!Number.isInteger(stepIndex) || stepIndex < 0 || stepIndex >= steps.length) {
    return <Navigate to={`/onboarding/${role}/1`} replace />
  }

  const meta = ROLE_SLUG_META[role]
  const current = steps[stepIndex]
  const profileSrc = user ?? MOCK_PROFILE[role]
  const templateVars: Record<string, string> = { name: profileSrc.name, position: profileSrc.position, dept: profileSrc.dept }

  const goNext = () => nav(`/onboarding/${role}/${stepIndex + 2}`)
  const finish = (to: string) => {
    completeOnboarding()
    nav(to)
  }

  return (
    <div className="onboarding-wrap" style={{ background: meta.bg }}>
      <div className="onboarding-topbar">
        <div className="row" style={{ gap: 8 }}>
          <div className="logo" style={{ width: 24, height: 24, borderRadius: 6, background: 'var(--sidebar-brand)' }} />
          <strong>TIGER</strong>
        </div>
        <span className="tag" style={{ background: meta.bg, color: meta.color, borderColor: 'transparent' }}>
          {meta.label} 온보딩
        </span>
      </div>

      <div className="onboarding-center">
        <div className="onboarding-card">
          {current.kind === 'intro' && (
            <>
              <div className="step-badge">{stepIndex + 1}</div>
              <h2>{current.title}</h2>
              <p>{current.description}</p>
            </>
          )}

          {current.kind === 'list' && (
            <>
              <h2>{current.title}</h2>
              <p>{current.description}</p>
              <div className="onboarding-list">
                {current.items.map((it) => (
                  <div className="item" key={it.label}>
                    <div style={{ textAlign: 'left' }}>
                      <div style={{ fontWeight: 600 }}>{it.label}</div>
                      <div className="text-meta">{it.sub}</div>
                    </div>
                    <span className="tag ok">{it.badge}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {current.kind === 'stats' && (
            <>
              <h2>{current.title}</h2>
              <p>{current.description}</p>
              <div className="onboarding-stats">
                {current.stats.map((s) => (
                  <div className="stat" key={s.label}>
                    <div className="text-meta">{s.label}</div>
                    <div className="value">{s.value}</div>
                  </div>
                ))}
              </div>
              {current.note && <div className="note">💡 {current.note}</div>}
            </>
          )}

          {current.kind === 'complete' && (
            <>
              <div className="step-badge" style={{ background: 'var(--tone-green-bg)', color: 'var(--tone-green)' }}>
                <Check size={20} />
              </div>
              <h2>{current.title}</h2>
              <p>{fillTemplate(current.description, templateVars)}</p>
            </>
          )}

          <div className="onboarding-dots">
            {steps.map((_, i) => (
              <span key={i} className={i === stepIndex ? 'active' : ''} />
            ))}
          </div>

          {current.kind === 'complete' ? (
            <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={() => finish(current.ctaTo)}>
              {current.ctaLabel} →
            </button>
          ) : (
            <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={goNext}>
              다음
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
