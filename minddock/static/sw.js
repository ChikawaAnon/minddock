/* MindDock service worker：只缓存应用静态壳（首页已是 CSS/JS 全内联的单文件）；
   API/附件永不进缓存（编辑型应用防脏数据）。
   发布新版改动静态资源后，把 CACHE 版本号 +1 即可强制刷新全部缓存。 */
const CACHE = "minddock-shell-v3";
const SHELL = ["./", "./manifest.webmanifest", "/portal/portal.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  // 数据与登录请求永远直连网络，绝不 respondWith 缓存
  if (url.pathname.includes("/api/") || url.pathname.includes("/attachments/")) return;
  // 静态壳：cache 优先 + 后台刷新（stale-while-revalidate，下一轮生效）
  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(e.request);
      const fresh = fetch(e.request).then((res) => {
        if (res && res.ok) cache.put(e.request, res.clone());
        return res;
      }).catch(() => cached);
      return cached || fresh;
    })
  );
});
