// O-1 로그인 — 인증 전 진입점(mock). 실제로는 SSO/JWT로 대체된다.
import { useNavigate } from 'react-router-dom'

const AGENTS = [
  { name: '초안 작성 Agent', desc: '영수증 인식·자동 분류' },
  { name: 'Rule Agent', desc: '확실한 건은 규정으로 즉시 판정' },
  { name: 'Risk Review Agent', desc: '애매한 건만 근거와 함께 선별' },
]

export function LoginScreen() {
  const nav = useNavigate()

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault()
    nav('/select-role')
  }

  return (
    <div className="auth-split">
      <div className="auth-brand-panel">
        <div className="logo" />
        <h1>
          법인카드 정산,
          <br />
          이제 AI가 먼저 확인합니다.
        </h1>
        <p className="lead">
          초안 작성부터 규정 검토, 위험 탐지까지
          <br />
          — 3개의 AI Agent가 정산 흐름의 80% 이상을 자동으로 처리하고, 사람은 애매한 건만 확인합니다.
        </p>
        <div className="agent-list">
          {AGENTS.map((a, i) => (
            <div key={a.name} className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
              <span className="num">{i + 1}</span>
              <div>
                <div className="name">{a.name}</div>
                <div className="desc">{a.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="auth-form-panel">
        <div className="auth-card">
          <h2>로그인</h2>
          <p className="text-meta" style={{ marginBottom: 20 }}>회사 계정으로 로그인하여 정산 플랫폼을 이용하세요.</p>

          <button type="button" className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={handleLogin}>
            회사 계정으로 로그인 (SSO)
          </button>

          <div className="auth-divider">또는</div>

          <form onSubmit={handleLogin}>
            <div className="field">
              <label>이메일</label>
              <input type="email" placeholder="name@tiger.co.kr" />
            </div>
            <div className="field">
              <label>비밀번호</label>
              <input type="password" placeholder="••••••••" />
            </div>
            <button type="submit" className="btn" style={{ width: '100%', justifyContent: 'center', background: 'var(--sidebar-bg)', color: '#fff', borderColor: 'var(--sidebar-bg)' }}>
              로그인
            </button>
          </form>

          <p className="text-meta" style={{ textAlign: 'center', marginTop: 16 }}>
            비밀번호를 잊으셨나요? 경영지원부 IT운영팀에 문의하세요.
          </p>
        </div>
      </div>
    </div>
  )
}
