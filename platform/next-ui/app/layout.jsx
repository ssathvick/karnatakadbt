import './style.css';
import './elegance.css';
import {LocaleProvider} from '../components/Locale';
export const metadata={title:'KarnatakaDBT | Workspace',description:'KarnatakaDBT Direct Benefit Transfer Fully AI Driven Automated Platform',manifest:'/registration/next/manifest.webmanifest',appleWebApp:{capable:true,title:'KarnatakaDBT',statusBarStyle:'default'},icons:{icon:'/assets/favicon.png',apple:'/registration/next/apple-touch-icon.png'}};
export const viewport={width:'device-width',initialScale:1,themeColor:'#a51d32'};
export default function Layout({children}){return <html lang="en"><body className="kdbt-next"><LocaleProvider>{children}</LocaleProvider></body></html>}
