// Only the generic offline message is cached. Account pages and APIs stay on the network.
const CACHE='karnatakadbt-offline-v1';
const OFFLINE='/registration/next/offline.html';
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.add(OFFLINE)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('karnatakadbt-offline-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',event=>{
  if(event.request.method==='GET'&&event.request.mode==='navigate'&&new URL(event.request.url).origin===self.location.origin){
    event.respondWith(fetch(event.request).catch(()=>caches.match(OFFLINE)));
  }
});
