// Service worker de la web del móvil: solo enseña los avisos que Delta manda por Web Push (avisos_web.py).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {texto: e.data ? e.data.text() : ''}; }
  fetch('/movil/ok?t=' + (d.t || 0)).catch(() => {});  // le dice al PC que el aviso ha llegado al móvil (queda en el log)
  e.waitUntil(self.registration.showNotification(d.titulo || 'Delta', {body: d.texto || '', tag: 'delta-' + (d.t || Date.now()), renotify: true}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({type: 'window'}).then(l => l.length ? l[0].focus() : self.clients.openWindow('/movil')));
});
