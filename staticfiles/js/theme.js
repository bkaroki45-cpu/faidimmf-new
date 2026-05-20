(function () {
    const storageKey = "faidii-theme";
    const root = document.documentElement;
    const darkIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 14.7A8.5 8.5 0 0 1 9.3 3a7 7 0 1 0 11.7 11.7Z" fill="currentColor"/></svg>';
    const lightIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="currentColor"/><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

    function safeStorageGet() {
        try {
            return localStorage.getItem(storageKey);
        } catch (error) {
            return null;
        }
    }

    function safeStorageSet(theme) {
        try {
            localStorage.setItem(storageKey, theme);
        } catch (error) {
            // Some mobile/private browsers can block storage. Theme still works for this page.
        }
    }

    function preferredTheme() {
        const saved = safeStorageGet();
        if (saved === "light" || saved === "dark") {
            return saved;
        }
        return "light";
    }

    function applyTheme(theme) {
        const nextTheme = theme === "dark" ? "dark" : "light";
        root.setAttribute("data-theme", nextTheme);
        safeStorageSet(nextTheme);
        const button = document.querySelector(".theme-toggle");
        if (button) {
            const targetTheme = nextTheme === "dark" ? "light" : "dark";
            button.innerHTML = nextTheme === "dark" ? lightIcon : darkIcon;
            button.setAttribute("aria-label", `Switch to ${targetTheme} mode`);
            button.setAttribute("title", `Switch to ${targetTheme} mode`);
        }
    }

    function createToggle() {
        if (document.querySelector(".theme-toggle")) {
            return;
        }
        const button = document.createElement("button");
        button.type = "button";
        button.className = "theme-toggle";
        button.addEventListener("click", function () {
            const nextTheme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
            applyTheme(nextTheme);
        });
        document.body.appendChild(button);
        applyTheme(root.getAttribute("data-theme") || preferredTheme());
    }

    applyTheme(preferredTheme());

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", createToggle);
    } else {
        createToggle();
    }
})();
