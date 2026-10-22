'use client';
import {createContext,useContext,useEffect,useState} from 'react';
import kannada from '../locales/kn.json';
const Context=createContext({language:'en',t:s=>s,setLanguage:()=>{}});
export const languages=[['en','English'],['kn','ಕನ್ನಡ']];
export function LocaleProvider({children}){
 const [language,setCurrent]=useState('en');
 function apply(code){if(!languages.some(([id])=>id===code))code='en';setCurrent(code);document.documentElement.lang=code;document.cookie=`KDBT-Language=${code}; Path=/; Max-Age=31536000; SameSite=Lax; Secure${location.hostname.endsWith('localhost:8443')?'; Domain=localhost:8443':''}`;const url=new URL(location.href);if(url.searchParams.has('lang')){url.searchParams.set('lang',code);history.replaceState(null,'',url.href)}try{localStorage.setItem('KDBT-Language',code)}catch{}window.dispatchEvent(new Event('kdbt:language'));}
 useEffect(()=>{const query=new URLSearchParams(location.search).get('lang');const cookie=document.cookie.match(/(?:^|; )KDBT-Language=(en|kn)(?:;|$)/)?.[1];apply(query||cookie||'en')},[]);
 useEffect(()=>{window.KDBTTranslations=kannada;if(!document.getElementById('kdbt-locale-chrome')){const script=document.createElement('script');script.id='kdbt-locale-chrome';script.src='/registration/static/locale-chrome.js?v=kn-1';document.body.append(script)}window.dispatchEvent(new Event('kdbt:language'))},[language]);
 const t=value=>language==='kn'?(kannada[value]||value):value;
 return <Context.Provider value={{language,setLanguage:apply,t}}>{children}</Context.Provider>;
}
export function useLocale(){return useContext(Context)}
export function LanguageSelector(){const {language,setLanguage}=useLocale();return <label className="language-selector"><span>Language / ಭಾಷೆ</span><select aria-label="Language / ಭಾಷೆ" value={language} onChange={e=>setLanguage(e.target.value)}>{languages.map(([code,label])=><option key={code} value={code} lang={code}>{label}</option>)}</select></label>}
