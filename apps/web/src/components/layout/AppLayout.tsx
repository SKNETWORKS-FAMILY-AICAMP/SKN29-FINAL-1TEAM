import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

// 시안 실측: 별도 상단바(알림·아바타) 없이 히어로 배너가 화면 최상단부터 시작한다.
// 사용자 아바타·알림·로그아웃·데모 역할전환은 모두 Sidebar가 소유한다.
export function AppLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-area">
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  )
}