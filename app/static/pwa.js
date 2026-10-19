if (
    "serviceWorker"
    in navigator
) {
    window.addEventListener(
        "load",
        async () => {

            try {

                await navigator
                    .serviceWorker
                    .register(
                        "/service-worker.js"
                    );

                console.log(
                    "Service worker registered"
                );

            }
            catch (error) {

                console.error(
                    "Service worker registration failed:",
                    error
                );

            }

        }
    );
}