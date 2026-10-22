'use client';
import {useLocale} from './Locale';

import {useEffect,useRef,useState} from 'react';
export const label=value=>String(value??'').replaceAll('_',' ');
export const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'}).format(value||0);
export async function request(path,body,signal){
  const response=await fetch('/registration/api/'+path,{credentials:'same-origin',cache:'no-store',signal,...(body?{method:'POST',body:new URLSearchParams(body)}:{})});
  const json=response.headers.get('content-type')?.includes('application/json')?await response.json():null;
  if(!response.ok||!json){const error=new Error(json?.error||json?.message||(response.status===403?'Your account cannot perform this action, or the session expired. Sign in again.':response.status===401?'Sign in to continue.':'The operation could not complete. Refresh the record before retrying.'));error.status=response.status;throw error}
  return json;
}
export function useApi(path){const [data,setData]=useState(null),[error,setError]=useState(null),[loading,setLoading]=useState(true),[version,setVersion]=useState(0);useEffect(()=>{const controller=new AbortController();setLoading(true);setError(null);setData(null);request(path,null,controller.signal).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});return()=>controller.abort()},[path,version]);return {data,error,loading,reload:()=>setVersion(v=>v+1)}}
export function LoadingError({resource}){const {t}=useLocale();return <>{resource.loading&&<p role="status">{t("Loading authorized records…")}</p>}{resource.error&&<div className="error" role="alert"><p>{t(resource.error.message)}</p><button onClick={resource.reload}>{t("Try again")}</button> <a href="/registration/login?mode=staff">{t("Staff sign in")}</a> · <a href="/registration/login?mode=beneficiary">{t("Beneficiary sign in")}</a></div>}</>}
export function JsonDetails({title,value}){const {t}=useLocale();return <details className="json-details"><summary>{t(title)}</summary><pre>{JSON.stringify(value,null,2)}</pre></details>}
export function ConfirmAction({title,description,busy,error,onConfirm,onCancel}){const {t}=useLocale();const dialog=useRef(null);useEffect(()=>{dialog.current?.showModal()},[]);return <dialog ref={dialog} aria-labelledby="programme-confirm-title" onCancel={e=>{if(busy)e.preventDefault();else onCancel()}}><h2 id="programme-confirm-title">{t(title)}</h2><p>{t(description)}</p>{error&&<p className="error" role="alert">{error}</p>}<div className="actions"><button disabled={busy} onClick={onConfirm}>{busy?'Submitting…':t("Confirm action")}</button><button className="secondary" disabled={busy} onClick={onCancel}>{t("Cancel")}</button></div></dialog>}
