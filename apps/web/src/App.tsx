import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { MyExpenses } from './screens/MyExpenses'
import { TeamAggregation } from './screens/TeamAggregation'
import { ReviewWorkspace } from './screens/ReviewWorkspace'
import { RuleConsole } from './screens/RuleConsole'
import { GovernanceDashboard } from './screens/GovernanceDashboard'

// 화면설계서 §1 화면 목록 ↔ 라우트 매핑
//  S-01 /my-expenses · S-02 /team · S-03 /review · S-04 /rules · S-05 /governance
//  S-06(정산 상세)는 공통 모달로 각 목록 화면에서 호출.
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/my-expenses" replace />} />
        <Route path="/my-expenses" element={<MyExpenses />} />
        <Route path="/team" element={<TeamAggregation />} />
        <Route path="/review" element={<ReviewWorkspace />} />
        <Route path="/rules" element={<RuleConsole />} />
        <Route path="/governance" element={<GovernanceDashboard />} />
        <Route path="*" element={<Navigate to="/my-expenses" replace />} />
      </Route>
    </Routes>
  )
}
