// Service worker de Delta móvil: solo muestra los avisos push (no cachea nada: sin casa, no hay Delta).
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json() } catch { d = {cuerpo: e.data?.text() || ""} }
  e.waitUntil(self.registration.showNotification(d.titulo || "Delta", {
    body: d.cuerpo || "", tag: d.tag || "delta", renotify: true, icon: "/icono.svg", badge: "/icono.svg", lang: "es",
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type: "window"}).then(ws => ws.length ? ws[0].focus() : clients.openWindow("/")));
});
