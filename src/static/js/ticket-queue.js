(() => {
    const root = document.querySelector("[data-ticket-request]");

    if (!root || !root.dataset.statusUrl) {
        return;
    }

    const statusBox = root.querySelector("[data-queue-status]");
    let stopped = false;

    const escapeHtml = (value) => {
        const node = document.createElement("div");
        node.textContent = value;
        return node.innerHTML;
    };

    const poll = async () => {
        if (stopped) {
            return;
        }

        try {
            const response = await fetch(root.dataset.statusUrl, {
                credentials: "same-origin",
                headers: {Accept: "application/json"},
                cache: "no-store",
            });

            if (!response.ok) {
                throw new Error("Ticket status request failed");
            }

            const data = await response.json();

            if (data.status === "pending") {
                const position = root.querySelector(
                    "[data-queue-position]"
                );
                if (position) {
                    position.textContent = data.queue_position;
                }
                window.setTimeout(poll, 750);
                return;
            }

            stopped = true;
            const message = escapeHtml(data.message || "Request completed.");
            const label = data.status === "succeeded"
                ? "View my tickets"
                : "Back to event";
            const href = escapeHtml(data.redirect_url || "/events/");

            statusBox.innerHTML = `
                <div>
                    <strong>${message}</strong>
                </div>
            `;
            root.querySelector(".queue-actions").innerHTML = `
                <a class="button" href="${href}">${label}</a>
            `;
        } catch (error) {
            window.setTimeout(poll, 2500);
        }
    };

    if (root.querySelector("[data-queue-position]")) {
        window.setTimeout(poll, 500);
    }
})();
