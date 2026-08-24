// 화면 단위 에러 바운더리 — **한 화면의 오류가 앱 전체를 흰 화면으로 만들지 않게.**
//
//  이게 없던 동안, 저장된 값의 모양이 코드가 기대하는 것과 다르기만 해도(예: Agent 산출물
//  스키마가 바뀐 뒤 남아 있는 과거 이력) React가 트리 전체를 언마운트해 **아무것도 안 보이는
//  상태**가 됐다. 사용자에게는 "고장"이고, 시연 중이면 되돌릴 방법도 없다.
//
//  **오류를 숨기지 않는다.** 사유를 화면에 그대로 남기고 콘솔에도 찍는다 — 조용히 빈 화면을
//  그리면 무엇이 잘못됐는지 아무도 모른다(이 저장소가 계속 피해 온 실패 방식).
//
//  이건 **안전망이지 방어 코드의 대체가 아니다.** 저장된 값을 읽는 쪽은 여전히 모양을
//  확인해야 한다(`RiskReportView.normalize` 참조) — 여기까지 오면 이미 한 번 놓친 것이다.
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface Props {
  children: ReactNode
  /** 어느 화면에서 났는지 — 사유 문구에 넣는다. */
  label?: string
}

interface State {
  error: Error | null
}

export class ScreenErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[화면 오류]', this.props.label ?? '', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="card" style={{ margin: 24, maxWidth: 720 }}>
        <div className="card-head">
          <h3 style={{ color: 'var(--tone-red)' }}>
            <AlertTriangle size={14} style={{ verticalAlign: '-2px' }} />{' '}
            화면을 그리지 못했습니다{this.props.label ? ` — ${this.props.label}` : ''}
          </h3>
        </div>
        <div className="card-body stack" style={{ gap: 12 }}>
          <div className="text-meta">
            저장된 데이터의 모양이 화면이 기대하는 것과 달라 렌더링이 중단됐습니다.
            다른 화면은 정상 동작합니다.
          </div>
          <pre
            className="text-meta"
            style={{
              margin: 0, padding: '8px 10px', overflowX: 'auto',
              background: 'var(--surface-2)', borderRadius: 'var(--radius-control)',
            }}
          >
            {error.message}
          </pre>
          <button
            className="btn primary"
            style={{ alignSelf: 'flex-start' }}
            onClick={() => this.setState({ error: null })}
          >
            <RotateCcw size={13} /> 다시 시도
          </button>
        </div>
      </div>
    )
  }
}
