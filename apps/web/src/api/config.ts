// 프론트 데이터 소스 스위치.
//  - 기본(mock=false): 실제 Django(/api) 데이터로 동작
//  - VITE_USE_MOCK=true: 화면이 data/mock.ts + 로컬 상태로 동작 (백엔드 불필요)
//  - VITE_USE_MOCK=false: 실제 Django(/api)에서 정산 데이터를 fetch하고 상태전이도 서버로 전송
//    (vite proxy가 /api → core:8000 로 프록시)
export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'false') === 'true'
