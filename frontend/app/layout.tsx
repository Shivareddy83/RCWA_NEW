import './globals.css'; import {AuthProvider} from '../lib/auth'; import {Shell} from '../components/ui';
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body><AuthProvider><Shell>{children}</Shell></AuthProvider></body></html>}
