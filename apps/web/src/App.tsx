import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { MyExpenses } from './screens/MyExpenses'
import { TeamAggregation } from './screens/TeamAggregation'
import { ReviewWorkspace } from './screens/ReviewWorkspace'
import { RuleConsole } from './screens/rule-console/RuleConsole'
import { GovernanceDashboard } from './screens/GovernanceDashboard'
import { AiLab } from './screens/ai-lab/AiLab'
// 규정 문서 관리는 임시 비활성화 — 재개 시 아래 import와 /policy-docs 라우트를 함께 복구한다.
// import { PolicyDocuments } from './screens/PolicyDocuments'
import { LoginScreen } from './screens/auth/LoginScreen'
import { RoleSelectScreen } from './screens/auth/RoleSelectScreen'
import { OnboardingWizard } from './screens/onboarding/OnboardingWizard'
import { ErpVoucherConfirm } from './screens/ErpVoucherConfirm'
import { useAuth } from './context/AuthContext'
import { ROLE_TO_SLUG } from './data/onboardingSteps'

// 미인증 시 /login, 로그인은 했지만 온보딩 전이면 본인 역할의 온보딩 1단계로 유도(mock 가드).
function RequireAuth({ children }: { children: ReactElement }) {
  const { isRestoring, isLoggedIn, hasOnboarded, user } = useAuth()
  if (isRestoring) return <div className="page"><div className="text-meta">로그인 세션을 확인하는 중입니다.</div></div>
  if (!isLoggedIn) return <Navigate to="/login" replace />
  if (!hasOnboarded) return <Navigate to={`/onboarding/${ROLE_TO_SLUG[user!.role]}/1`} replace />
  return children
}

// 화면설계서 §1 화면 목록 ↔ 라우트 매핑
//  O-1 /login · R-0 /select-role · EMP/ACC/EXE /onboarding/:role/:step
//  S-01 /my-expenses · S-02 /team · S-03 /review · S-04 /rules · S-05 /governance
//  S-06(정산 상세)는 공통 모달로 각 목록 화면에서 호출.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/select-role" element={<RoleSelectScreen />} />
      <Route path="/onboarding/:role/:step" element={<OnboardingWizard />} />

      {/* F-4: 사이드바 없는 풀스크린 플로우(로그인은 필요). 신규 지출 등록은 S-01 통합 모달로 대체됨 */}
      <Route path="/erp/:id" element={<RequireAuth><ErpVoucherConfirm /></RequireAuth>} />

      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route index element={<Navigate to="/my-expenses" replace />} />
        <Route path="/my-expenses" element={<MyExpenses />} />
        <Route path="/team" element={<TeamAggregation />} />
        <Route path="/review" element={<ReviewWorkspace />} />
        <Route path="/rules" element={<RuleConsole />} />
        {/* <Route path="/policy-docs" element={<PolicyDocuments />} /> — 임시 비활성화(아래 catch-all이 /my-expenses로 보냄) */}
        <Route path="/governance" element={<GovernanceDashboard />} />
        {/* AI-LAB(관리자) — AI 기능 독립 실행. 사이드바 노출은 Capability `ai_lab`로 게이트. */}
        <Route path="/ai-lab" element={<AiLab />} />
        <Route path="*" element={<Navigate to="/my-expenses" replace />} />
      </Route>
    </Routes>
  )
}
