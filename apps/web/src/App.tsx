import { useEffect, useState } from 'react'
import { api } from './api/client'

// 스캐폴드 확인용 최소 화면: core 헬스체크 결과를 표시.
export default function App() {
  const [health, setHealth] = useState<string>('checking...')

  useEffect(() => {
    api
      .get('/health/')
      .then((res) => setHealth(JSON.stringify(res.data)))
      .catch((err) => setHealth('error: ' + err.message))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: 32, lineHeight: 1.6 }}>
      <h1>법인카드 정산 자동화 플랫폼</h1>
      <p>모노레포 스캐폴드 (React · Django · FastAPI · Chroma · PostgreSQL)</p>
      <h2>Core API health</h2>
      <pre style={{ background: '#f4f4f4', padding: 12, borderRadius: 8 }}>{health}</pre>
    </main>
  )
}
