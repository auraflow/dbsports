const CACHE_NAME = 'dbsports-cache-v3'; // Версия 3

// 1. Установка: сразу активируем и сохраняем стили
self.addEventListener('install', event => {
    self.skipWaiting(); 
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(['/', '/static/css/style.css']);
        })
    );
});

// 2. Активация: захватываем контроль над страницей НЕМЕДЛЕННО и чистим старый кэш
self.addEventListener('activate', event => {
    event.waitUntil(self.clients.claim()); 
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) return caches.delete(cacheName);
                })
            );
        })
    );
});

// 3. Перехват запросов
self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET' || event.request.url.includes('/admin/')) return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                if (response.status === 200) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseClone));
                }
                return response;
            })
            .catch(() => {
                // ВАЖНО: ignoreVary: true спасает от конфликта заголовков Django!
                return caches.match(event.request, { ignoreVary: true })
                    .then(cachedResponse => {
                        if (cachedResponse) return cachedResponse;
                        
                        // Если страницы всё же нет в кэше, отдаем красивую заглушку в стиле темной темы, а не ошибку браузера
                        return new Response(
                            '<div style="font-family:sans-serif; text-align:center; background:#2b2b2b; color:#fff; height:100vh; padding-top:10vh;">' +
                            '<h2 style="color:#ffc107;">🌐 Нет связи с сервером</h2>' +
                            '<p style="color:#aaa;">Эта страница не была сохранена в памяти устройства для офлайн-доступа.</p>' +
                            '<button onclick="window.history.back()" style="padding:10px 20px; background:#ffc107; color:#000; border:none; border-radius:5px; font-weight:bold; cursor:pointer; margin-top:20px;">← Вернуться назад</button>' +
                            '</div>',
                            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                        );
                    });
            })
    );
});