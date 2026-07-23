import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import { RoleProvider } from './context/RoleContext'
import { SettlementsProvider } from './context/SettlementsContext'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <RoleProvider>
          <SettlementsProvider>
            <App />
          </SettlementsProvider>
        </RoleProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
