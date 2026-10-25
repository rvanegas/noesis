import axios from 'axios'
import { Amplify } from 'aws-amplify'
import { fetchAuthSession } from 'aws-amplify/auth'

// Sign-in is Roxana's: the same Cognito user pool, through noesis's own app
// client. dianoia requires a caller on every route, and verifies the ID token
// sent here against that pool (rvanegas-site SITE.md, Phase 4).
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
    },
  },
})

// Every request noesis makes is to dianoia, and all of them go through axios,
// so this is the one place the token is attached. fetchAuthSession refreshes
// an expired token first.
axios.interceptors.request.use(async (config) => {
  const idToken = (await fetchAuthSession()).tokens?.idToken?.toString()
  if (idToken) config.headers.Authorization = `Bearer ${idToken}`
  return config
})
