import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'

// Vite removes the unused branch and its imports from each static build.
const entry = import.meta.env.MODE === 'replay' ? import('./ReplayApp') : import('./App')
entry.then(({ default: App }) => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode><App /></React.StrictMode>,
  )
})
