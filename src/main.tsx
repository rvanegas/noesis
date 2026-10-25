import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Authenticator } from '@aws-amplify/ui-react'
import '@aws-amplify/ui-react/styles.css'
import './auth'
import './index.css'
import App from './App.tsx'

// Accounts are made in Roxana, so there is no sign-up here.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Authenticator hideSignUp>
      {({ signOut, user }) => (
        <>
          <App />
          <div className="fixed bottom-2 right-3 z-50 text-xs text-slate-500 dark:text-zinc-400">
            {user?.username} ·{' '}
            <button className="underline hover:text-slate-800 dark:hover:text-zinc-200" onClick={signOut}>
              sign out
            </button>
          </div>
        </>
      )}
    </Authenticator>
  </StrictMode>
)
