// AI-LAB 공용 표시 조각 — 실험 화면은 "요약"보다 "원본"이 중요하다.
//  결과 JSON·프롬프트·오류 문구를 잘라내지 않고 그대로 보여주되, 접기/복사로 길이를 다룬다.
import { useState, type ReactNode } from 'react'
import { AlertTriangle, Check, ChevronDown, ChevronRight, Copy } from 'lucide-react'

/** 접이식 섹션 — 추적·원본 JSON처럼 "필요할 때만 펼치는" 상세를 담는다. */
export function Collapsible({
  title,
  meta,
  defaultOpen = false,
  children,
}: {
  title: ReactNode
  meta?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="lab-collapsible">
      <button className="lab-collapsible-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="lab-collapsible-title">{title}</span>
        {meta && <span className="text-meta" style={{ marginLeft: 'auto' }}>{meta}</span>}
      </button>
      {open && <div className="lab-collapsible-body">{children}</div>}
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="btn sm"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => {
            setDone(true)
            window.setTimeout(() => setDone(false), 1200)
          },
          () => undefined,
        )
      }}
      title="클립보드로 복사"
    >
      {done ? <Check size={11} /> : <Copy size={11} />} {done ? '복사됨' : '복사'}
    </button>
  )
}

/** 원본 문자열(프롬프트·LLM 출력) 그대로. 줄바꿈·공백을 보존해야 프롬프트 검증이 된다. */
export function TextBlock({ text, label, maxHeight = 320 }: { text: string; label?: string; maxHeight?: number }) {
  return (
    <div className="lab-block">
      <div className="lab-block-head">
        <span className="text-meta">{label ?? '원본'}</span>
        <span className="text-meta">{text.length.toLocaleString()}자</span>
        <CopyButton text={text} />
      </div>
      <pre className="lab-pre" style={{ maxHeight }}>{text}</pre>
    </div>
  )
}

/** JSON 원본 — 화면이 해석한 값이 아니라 서버가 실제로 준 것. */
export function JsonBlock({ value, label, maxHeight = 320 }: { value: unknown; label?: string; maxHeight?: number }) {
  const text = JSON.stringify(value, null, 2)
  return <TextBlock text={text} label={label ?? 'JSON 원본'} maxHeight={maxHeight} />
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="lab-error" role="alert">
      <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
      <div>
        <div style={{ fontWeight: 700, marginBottom: 2 }}>실행 실패</div>
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{message}</div>
      </div>
    </div>
  )
}

export function StatusDot({ ok, label, hint }: { ok: boolean; label: string; hint?: string }) {
  return (
    <span className={'lab-status-dot' + (ok ? ' ok' : ' bad')} title={hint}>
      <span className="dot" />
      {label}
    </span>
  )
}

/** 라벨 = 값 나열. 추적 지표(모델·지연·토큰)처럼 짧은 사실을 촘촘히 늘어놓을 때. */
export function FactRow({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="lab-facts">
      {items.map(([k, v]) => (
        <div key={k} className="lab-fact">
          <span className="k">{k}</span>
          <span className="v">{v}</span>
        </div>
      ))}
    </div>
  )
}

export function EmptyHint({ children }: { children: ReactNode }) {
  return <div className="lab-empty">{children}</div>
}

/** 탭 상단 고정 안내 — 경고와 사용법 안내를 색으로 갈라 쓰던 것을 하나로 통일한다.
 *  (실행하면 실제 부작용이 있다는 것도, 파일을 여기서 못 올린다는 것도 "이 탭을 쓰기
 *  전에 알아야 할 것"이라는 같은 종류의 정보라 같은 모양이어야 한다.) */
export function TabNote({ children }: { children: ReactNode }) {
  return <div className="lab-tab-note">{children}</div>
}
