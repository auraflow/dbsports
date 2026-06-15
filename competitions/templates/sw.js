const CACHE_NAME = 'dbsports-cache-v6'; // Обновляем версию для принудительной перезаписи

// 1. Установка: сразу активируем и сохраняем критически важную статику
self.addEventListener('install', event => {
    self.skipWaiting(); 
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll([
                '/', 
                '/static/css/style.css',
                '/manifest.json'
            ]);
        })
    );
});

// 2. Активация: захватываем контроль и чистим старый кэш
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

// 3. Перехват запросов (Двойная стратегия)
self.addEventListener('fetch', event => {
    // Игнорируем не-GET запросы и админку
    if (event.request.method !== 'GET' || event.request.url.includes('/admin/')) return;

    const requestUrl = new URL(event.request.url);

    // ВЕТКА А: Стратегия "Cache First" (Сначала кэш) для статики и внешних шрифтов
    if (
        requestUrl.pathname.startsWith('/static/') || 
        requestUrl.pathname.includes('manifest.json') ||
        requestUrl.hostname === 'fonts.googleapis.com' ||
        requestUrl.hostname === 'fonts.gstatic.com'
    ) {
        event.respondWith(
            caches.match(event.request, { ignoreVary: true }).then(cachedResponse => {
                if (cachedResponse) return cachedResponse; // Мгновенная отдача из кэша
                
                // Если в кэше пусто (первый заход), качаем из сети и сохраняем
                return fetch(event.request).then(networkResponse => {
                    if (networkResponse.status === 200) {
                        const clone = networkResponse.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return networkResponse;
                });
            })
        );
        return; // Прерываем выполнение, чтобы не сработала вторая ветка
    }

    // ВЕТКА Б: Стратегия "Network First" (Сначала сеть) для HTML-страниц
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
                // Если сеть отвалилась, ищем сохраненную HTML-страницу в кэше
                return caches.match(event.request, { ignoreVary: true })
                    .then(cachedResponse => {
                        if (cachedResponse) return cachedResponse;
                        
                        // Если страницы нет в кэше, отдаем красивую офлайн-заглушку
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