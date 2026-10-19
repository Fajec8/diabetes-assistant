const CACHE_NAME =
    "diabetes-assistant-shell-v1";


const APP_SHELL = [
    "/app",
    "/manifest.webmanifest",
    "/static/pwa.js"
];


self.addEventListener(
    "install",
    event => {

        event.waitUntil(
            caches
                .open(
                    CACHE_NAME
                )
                .then(
                    cache =>
                        cache.addAll(
                            APP_SHELL
                        )
                )
        );

        self.skipWaiting();
    }
);


self.addEventListener(
    "activate",
    event => {

        event.waitUntil(
            caches
                .keys()
                .then(
                    cacheNames =>
                        Promise.all(
                            cacheNames
                                .filter(
                                    name =>
                                        name
                                        !== CACHE_NAME
                                )
                                .map(
                                    name =>
                                        caches.delete(
                                            name
                                        )
                                )
                        )
                )
        );

        self.clients.claim();
    }
);


self.addEventListener(
    "fetch",
    event => {

        const request =
            event.request;

        if (
            request.method
            !== "GET"
        ) {
            return;
        }

        const url =
            new URL(
                request.url
            );

        if (
            url.origin
            !== self.location.origin
        ) {
            return;
        }


        /*
         * Cachujeme jen samotne UI.
         *
         * Necachujeme:
         * /auth
         * /glucose
         * /meals
         * /insulin
         * /activities
         * /situations
         *
         * Tedy zadna zdravotni data.
         */

        const isAppShell =
            (
                url.pathname
                === "/app"
                ||
                url.pathname
                === "/manifest.webmanifest"
                ||
                url.pathname
                    .startsWith(
                        "/static/"
                    )
            );

        if (!isAppShell) {
            return;
        }


        event.respondWith(
            fetch(
                request
            )
                .then(
                    response => {

                        const copy =
                            response.clone();

                        caches
                            .open(
                                CACHE_NAME
                            )
                            .then(
                                cache =>
                                    cache.put(
                                        request,
                                        copy
                                    )
                            );

                        return response;
                    }
                )
                .catch(
                    () =>
                        caches.match(
                            request
                        )
                )
        );
    }
);