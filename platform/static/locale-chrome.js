/* Only first-party shell labels. Never traverses forms, records or article text. */
(()=>{'use strict';if(window.KDBTLocaleChrome)return;window.KDBTLocaleChrome=true;
 const originals=new WeakMap();let scheduled=false;
 function apply(){scheduled=false;const kn=document.documentElement.lang==='kn',dict=window.KDBTTranslations||{};
  for(const node of document.querySelectorAll('#ka2p-platform-bar a:not(.ka2p-platform-brand),#ka2p-platform-bar button,#ka2p-platform-bar .ka2p-platform-module,#ka2p-platform-guide h2,#ka2p-platform-guide button,#ng-km-launcher')){
   if(!originals.has(node))originals.set(node,node.textContent);const original=originals.get(node),text=kn?(dict[original]||original):original;if(node.textContent!==text)node.textContent=text;node.lang=kn&&dict[original]?'kn':'en';
  }
 }
 function schedule(){if(!scheduled){scheduled=true;queueMicrotask(apply)}}
 window.addEventListener('kdbt:language',schedule);document.addEventListener('DOMContentLoaded',schedule);new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});schedule();
})();
