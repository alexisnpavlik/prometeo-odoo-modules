(function () {
    // POC Error Tracking using native APIs (Fase 1)
    window.addEventListener("error", function (event) {
        const error = event.error;
        const message = event.message || (error && error.message) || "Unknown Error";
        const filename = event.filename || "unknown";
        const lineno = event.lineno || 0;
        const colno = event.colno || 0;
        const stack = error && error.stack ? error.stack : "";

        console.log(
            `[POS ERROR]\n` +
            `Message: ${message}\n` +
            `File: ${filename}:${lineno}:${colno}\n` +
            `Stack: ${stack || "No stack trace available"}`
        );
    });

    window.addEventListener("unhandledrejection", function (event) {
        const reason = event.reason;
        const message = (reason && (reason.message || reason)) || "Unknown Promise Rejection";
        const stack = reason && reason.stack ? reason.stack : "";

        console.log(
            `[POS UNHANDLED PROMISE]\n` +
            `Reason: ${message}\n` +
            `Stack: ${stack || "No stack trace available"}`
        );
    });
})();
