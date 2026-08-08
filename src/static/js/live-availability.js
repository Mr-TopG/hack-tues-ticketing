(() => {
    const root = document.querySelector("[data-live-availability]");

    if (!root || !root.dataset.availabilityUrl) {
        return;
    }

    let timer = null;

    const schedule = (delay = 2000) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(refresh, delay);
    };

    const updateCategory = (availability) => {
        const category = root.querySelector(
            `[data-category-id="${availability.id}"]`
        );

        if (!category) {
            return;
        }

        const count = category.querySelector("[data-available-count]");
        const capacity = category.querySelector("[data-capacity-count]");
        const availableAction = category.querySelector(
            "[data-available-action]"
        );
        const soldOutAction = category.querySelector(
            "[data-sold-out-action]"
        );
        const unavailableAction = category.querySelector(
            "[data-registration-unavailable-action]"
        );
        const unavailableNote = category.querySelector(
            "[data-registration-unavailable-note]"
        );
        const badge = category.querySelector(
            "[data-registration-badge]"
        );
        const soldOut = availability.available <= 0;
        const registrationOpen = (
            availability.registration_state === "open"
        );

        if (count) {
            count.textContent = availability.available;
        }
        if (capacity) {
            capacity.textContent = availability.capacity;
        }
        if (availableAction) {
            availableAction.hidden = soldOut || !registrationOpen;
        }
        if (soldOutAction) {
            soldOutAction.hidden = !soldOut || !registrationOpen;
        }
        if (unavailableAction) {
            unavailableAction.hidden = registrationOpen;
        }
        if (unavailableNote && !registrationOpen) {
            unavailableNote.textContent = (
                availability.registration_state === "upcoming"
            ) ? "Registration opens later" : "Registration closed";
        }
        if (badge) {
            badge.className = (
                `status-badge status-${availability.registration_state}`
            );
            badge.textContent = availability.registration_state
                .replace("_", " ")
                .replace(/^./, (letter) => letter.toUpperCase());
        }
    };

    async function refresh() {
        if (document.hidden) {
            schedule(3000);
            return;
        }

        try {
            const response = await fetch(root.dataset.availabilityUrl, {
                credentials: "same-origin",
                headers: {Accept: "application/json"},
                cache: "no-store",
            });

            if (!response.ok) {
                throw new Error("Availability request failed");
            }

            const data = await response.json();
            data.categories.forEach(updateCategory);
            schedule();
        } catch (error) {
            schedule(5000);
        }
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            schedule(0);
        }
    });
    schedule();
})();
