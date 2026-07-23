import type { ReactNode } from 'react'
import { useEffect, useId, useRef } from 'react'
import { X } from 'lucide-react'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function Modal({
  title,
  onClose,
  children,
  footer,
  maxWidth,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** 기본 880px. 그래프/트리 탐색기처럼 넓은 콘텐츠에 사용(예: 1360). */
  maxWidth?: number
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  // Esc 닫기, Tab 포커스 트랩, 최초 포커스 이동, 닫힐 때 이전 포커스 복귀.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
    focusable?.[0]?.focus()

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab' || !focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previouslyFocused?.focus()
    }
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={dialogRef}
        style={maxWidth ? { maxWidth } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3 id={titleId}>{title}</h3>
          <button className="x-btn" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}
