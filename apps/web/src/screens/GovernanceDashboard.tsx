// S-05 거버넌스 대시보드 — 회계/운영 상부. FR-UI-05, FR-DB-05~08
// 프로토타입 단계: 빈 상태(틀만). 지표·차트·인사이트는 추후 연동한다.
export function GovernanceDashboard() {
  return (
    <>
      <div className="page-head">
        <span className="screen-id">S-05</span>
        <h1>거버넌스 대시보드</h1>
        <div className="sub">지출 추세·예산 소진율·정책 인사이트를 제공합니다. 예산은 경고성 지표이며 자동 차단하지 않습니다.</div>
      </div>

      <div className="filter-bar">
        <select disabled><option>2026 Q2</option></select>
        <select disabled><option>본부: 전체</option></select>
      </div>

      {/* KPI 자리 (빈 스켈레톤) */}
      <div className="kpi-grid">
        {['총 지출액', '예산 소진율', '자동처리율', '정책위반 의심'].map((label) => (
          <div className="kpi" key={label}>
            <div className="label">{label}</div>
            <div className="value muted">—</div>
          </div>
        ))}
      </div>

      {/* 콘텐츠 자리 (빈 상태 안내) */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        {['분류별 지출 추세', '본부별 예산 소진율'].map((title) => (
          <div className="card" key={title}>
            <div className="card-head"><h3>{title}</h3></div>
            <div className="card-body" style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="text-meta">데이터 연동 예정</span>
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-body" style={{ textAlign: 'center', padding: '40px 24px' }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>대시보드 준비 중</div>
          <div className="text-meta">
            반려 사유 Top5 · 정책 인사이트 추천 · 리스크 패턴 알림(분할결제 등)이 이 영역에 표시됩니다. (프로토타입: 틀만 구성)
          </div>
        </div>
      </div>
    </>
  )
}
