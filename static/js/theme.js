(function () {
    const storageKey = "faidii-theme";
    const root = document.documentElement;

    function preferredTheme() {
        const saved = localStorage.getItem(storageKey);
        if (saved === "light" || saved === "dark") {
            return saved;
        }
        return "dark";
    }

    function applyTheme(theme) {
        root.setAttribute("data-theme", theme);
        localStorage.setItem(storageKey, theme);
        const button = document.querySelector(".theme-toggle");
        if (button) {
            button.textContent = theme === "dark" ? "Light mode" : "Dark mode";
            button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
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
