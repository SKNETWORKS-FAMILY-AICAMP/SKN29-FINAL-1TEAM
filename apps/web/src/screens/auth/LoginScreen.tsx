// O-1 로그인 — 랜딩(좌) + 로그인 폼(우). 회원가입 없음.
//  - mock 모드: 폼 제출 시 역할 선택(R-0)으로 이동
//  - 실 모드(USE_MOCK=false): 사원번호(username)/비밀번호로 Django 세션 로그인
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { USE_MOCK } from '../../api/config'
import { useAuth } from '../../context/AuthContext'

const AGENTS = [
  { name: '초안 작성 Agent', desc: '영수증 인식·자동 분류' },
  { name: 'Rule Agent', desc: '확실한 건은 규정으로 즉시 판정' },
  { name: 'Risk Review Agent', desc: '애매한 건만 근거와 함께 선별' },
]

export function LoginScreen() {
  const nav = useNavigate()
  const { loginWithCredentials } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (USE_MOCK) {
      nav('/select-role')
      return
    }
    setBusy(true)
    setErr('')
    try {
      await loginWithCredentials(username, password)
      nav('/my-expenses')
    } catch {
      setErr('사원번호 또는 비밀번호가 올바르지 않습니다.')
    } finally {
      setBusy(false)
    }
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

          {USE_MOCK && (
            <>
              <button type="button" className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={handleLogin}>
                회사 계정으로 로그인 (SSO)
              </button>
              <div className="auth-divider">또는</div>
            </>
          )}

          <form onSubmit={handleLogin}>
            <div className="field">
              <label>사원번호</label>
              <input type="text" placeholder={USE_MOCK ? 'xxxxxxxx' : '예) kim · lead · acc · acclead · exec'}
                     value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </div>
            <div className="field">
              <label>비밀번호</label>
              <input type="password" placeholder="••••••••"
                     value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            </div>
            {err && <p className="text-meta" style={{ color: 'var(--tone-red)', marginTop: -8, marginBottom: 12 }}>{err}</p>}
            <button type="submit" disabled={busy} className="btn"
                    style={{ width: '100%', justifyContent: 'center', background: 'var(--sidebar-bg)', color: '#fff', borderColor: 'var(--sidebar-bg)' }}>
              {busy ? '로그인 중…' : '로그인'}
            </button>
          </form>

          <p className="text-meta" style={{ textAlign: 'center', marginTop: 16 }}>
            비밀번호를 잊으셨나요? 경영지원본부 IT운영부에 문의하세요.
          </p>
        </div>
      </div>
    </div>
  )
}
