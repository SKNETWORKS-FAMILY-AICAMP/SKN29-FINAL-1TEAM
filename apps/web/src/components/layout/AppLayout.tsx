import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { ScreenErrorBoundary } from './ScreenErrorBoundary'

// 시안 실측: 별도 상단바(알림·아바타) 없이 히어로 배너가 화면 최상단부터 시작한다.
// 사용자 아바타·알림·로그아웃·데모 역할전환은 모두 Sidebar가 소유한다.
export function AppLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-area">
        <main className="page">
          {/*  **한 화면의 오류가 앱 전체를 흰 화면으로 만들지 않게.** 라우트마다 감싸지 않고
              여기 한 번만 두는 이유: 사이드바는 살아 있어야 다른 화면으로 빠져나갈 수 있다. */}
          <ScreenErrorBoundary>
            <Outlet />
          </ScreenErrorBoundary>
        </main>
      </div>
    </div>
  )
}