export default function WorkspaceIcon({name='Overview',className=''}){
  const paths={
    Overview:<><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    Households:<><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M9 21v-8h6v8"/></>,
    Registration:<><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 10h8M8 14h4M15 15v5m-2.5-2.5h5"/></>,
    Programmes:<><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3"/></>,
    Payments:<><rect x="2" y="5" width="20" height="15" rx="3"/><path d="M2 10h20M6 15h4m6 0h2"/></>,
    Analytics:<><path d="M4 3v18h17M8 16v-5m5 5V6m5 10v-8"/></>,
    Knowledge:<><path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1Zm0 0v15"/></>,
    Services:<><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h10M5 7v10m14-10v10M7 19h10"/></>,
    Map:<><path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2Zm6-2v16m6-14v16"/></>,
    Check:<path d="m5 12 4 4L19 6"/>,
    Arrow:<path d="M4 12h16m-6-6 6 6-6 6"/>,
  };
  return <svg className={'workspace-icon '+className} width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]||paths.Services}</svg>
}
