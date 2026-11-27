import { useEffect, useState } from 'react'
import App from './App.tsx'
import StaffView from './StaffView.tsx'

/** '#staff' shows the staff approval page; anything else is the customer chat. */
export default function Root() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash === '#staff' ? <StaffView /> : <App />
}
