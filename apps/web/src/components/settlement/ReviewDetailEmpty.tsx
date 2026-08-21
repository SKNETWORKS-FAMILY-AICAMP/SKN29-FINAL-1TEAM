// 검토 워크스페이스(S-03) 상세·AI 검토 패널의 **빈 상태**.
//
// 목록이 비었거나 아무것도 선택되지 않았을 때 오른쪽 절반이 통째로 사라지면 화면이
// 반쪽으로 접혔다가 건이 생기는 순간 다시 펴진다 — 같은 화면을 보고 있는데 레이아웃이
// 두 벌이라, 담당자는 "지금 뭐가 안 나온 건지"를 매번 다시 파악해야 한다.
//
// 그래서 **실제 패널과 같은 골격**(좌: 상세·판정입력값·이력 / 우: ①이상탐지 ②RAG검증
// ③결정)을 그대로 유지하고, 내용만 자리표시자로 둔다. 자리가 고정돼 있으면 건을 고를 때
// 시선이 움직이지 않는다.
//
// **가짜 값을 넣지 않는다.** 점수는 `-`, 배지는 회색, 버튼은 비활성 — 빈 상태를 채우려고
// `0.00`이나 '승인 권장' 같은 값을 그려 넣으면 그게 곧 판단으로 읽힌다(승인대기 건의
// anomaly를 0으로 그리던 것과 같은 실수다).
export function ReviewDetailEmpty({ message }: { message: string }) {
  return (
    <div className="review-detail grid-2">
      {/* ───────── 좌: 상세 + 판정 입력값 + 이력 ───────── */}
      <div className="stack">
        <div className="card">
          <div className="card-head">
            <h3>선택 건 상세</h3>
            <span className="text-meta">-</span>
          </div>
          <div className="card-body">
            <div className="text-meta" style={{ marginBottom: 6 }}>영수증 이미지</div>
            <div style={{
              height: 160, border: '1px dashed var(--border-strong)', borderRadius: 'var(--radius-control)',
              background: 'var(--surface-2)', display: 'flex', alignItems: 'center',
              justifyContent: 'center', color: 'var(--muted)', fontSize: 13,
            }}>
              {message}
            </div>
            <div className="grid-2" style={{ marginTop: 12 }}>
              {['가맹점', '거래일시', '금액', '비용분류'].map((label) => (
                <div className="field" key={label}>
                  <label>{label}</label>
                  <input value="" placeholder="-" readOnly disabled />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3>fact.json</h3>
            <span className="text-meta">규정 판정 입력값</span>
          </div>
          <div className="card-body text-meta">건을 선택하면 판정 시점의 사실 스냅샷이 표시됩니다.</div>
        </div>

        <div className="card">
          <div className="card-head"><h3>상태 변경 이력</h3></div>
          <div className="card-body text-meta">-</div>
        </div>
      </div>

      {/* ───────── 우: ①이상탐지 + ②RAG검증 + ③결정 ───────── */}
      <div className="stack">
        <div className="card">
          <div className="card-head">
            <h3>① 이상탐지 결과</h3>
            <span className="tag" style={{ color: 'var(--muted)' }}>anomaly -</span>
          </div>
          <div className="card-body text-meta">건을 선택하면 이상 신호와 Feature 기여도가 표시됩니다.</div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3>② RAG 내규 검증</h3>
            <span className="tag" style={{ color: 'var(--muted)' }}>AI 권장 -</span>
          </div>
          <div className="card-body text-meta">건을 선택하면 내규·유사사례 근거가 표시됩니다.</div>
        </div>

        <div className="card">
          <div className="card-head"><h3>③ 검토 결정</h3></div>
          <div className="card-body">
            {/* 버튼 자리를 비워두지 않는다 — 있다가 없어지면 눌러야 할 곳이 매번 바뀐다. */}
            <div className="row review-actions">
              <button className="btn approve" disabled>승인</button>
              <button className="btn return" disabled>보완요청</button>
              <button className="btn reject" disabled>반려(최종)</button>
            </div>
            <div className="text-meta" style={{ marginTop: 10, textAlign: 'right' }}>{message}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
