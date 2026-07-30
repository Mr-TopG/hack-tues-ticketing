(() => {
    const root = document.documentElement;
    const toggle = document.querySelector("[data-theme-toggle]");
    const menu = document.querySelector(".nav-menu");
    const mobileNavigation = window.matchMedia("(max-width: 1000px)");

    const syncNavigation = (mediaQuery) => {
        if (!menu) {
            return;
        }

        if (mediaQuery.matches) {
            menu.removeAttribute("open");
        } else {
            menu.setAttribute("open", "");
        }
    };

    syncNavigation(mobileNavigation);
    mobileNavigation.addEventListener("change", syncNavigation);

    if (!toggle) {
        return;
    }

    const applyTheme = (theme) => {
        root.dataset.theme = theme;
        root.style.colorScheme = theme;

        const themeColor = document.querySelector(
            'meta[name="theme-color"]'
        );

        if (themeColor) {
            themeColor.setAttribute(
                "content",
                theme === "dark" ? "#050a13" : "#e8edf4"
            );
        }

        const nextTheme = theme === "dark" ? "light" : "dark";
        const nextLabel = `Switch to ${nextTheme} theme`;

        toggle.setAttribute("aria-label", nextLabel);
        toggle.setAttribute("title", nextLabel);
    };

    applyTheme(root.dataset.theme || "light");

    toggle.addEventListener("click", () => {
        const nextTheme = (
            root.dataset.theme === "dark" ? "light" : "dark"
        );

        try {
            localStorage.setItem("ticketing-theme", nextTheme);
        } catch (error) {
            // The theme still changes when browser storage is unavailable.
        }

        applyTheme(nextTheme);
    });
})();
