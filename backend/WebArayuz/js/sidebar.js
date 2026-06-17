/**
 * sidebar.js - Self-Contained Sidebar
 * fetch KULLANMAZ, HTML doğrudan JS içinde üretilir.
 */
(function () {
    "use strict";

    function getCurrentPage() {
        var path = window.location.pathname;
        return path.split("/").pop().replace(".html", "") || "index";
    }

    function injectSidebar() {
        var container = document.getElementById("sidebar-container");
        if (!container) return;

        var page    = getCurrentPage();
        var isAdmin = (typeof Auth !== "undefined" && Auth.isAdmin) ? Auth.isAdmin() : false;
        var user    = (typeof Auth !== "undefined" && Auth.getUser) ? Auth.getUser() : null;

        var userName = user ? (user.full_name || user.username || "User") : "User";
        var userRole = user ? (user.role === "admin" ? "Yönetici" : "Kullanıcı") : "";
        var initials = "?";
        if (userName && userName.length > 0) {
            initials = userName.split(" ").map(function(n){ return n[0]; }).join("").toUpperCase().slice(0, 2);
        }

        function item(pg, icon, label) {
            var cls = (pg === page) ? "nav-item active" : "nav-item";
            return '<a href="' + pg + '.html" class="' + cls + '" data-page="' + pg + '">'
                + '<span class="nav-item-icon">' + icon + '</span>'
                + '<span>' + label + '</span></a>';
        }

        function section(title, items) {
            return '<div class="nav-section">'
                + '<div class="nav-section-title">' + title + '</div>'
                + items
                + '</div>';
        }

        var adminBlock = "";
        if (isAdmin) {
            adminBlock = section(
                "Admin",
                item("admin-repos",      "&#128295;", "Repo Yönetimi")
                + item("admin-users",    "&#128101;", "Kullanıcılar")
                + item("admin-scenarios","&#128193;", "Senaryolar")
                + item("admin-stats",    "&#128202;", "Koşum İstatistikleri")
                + item("admin-logs",     "&#128203;", "Koşum Logları")
            );
        }

        var html = ''
            + '<aside class="sidebar">'
            +   '<div class="sidebar-header">'
            +     '<div class="logo">'
            +       '<div class="logo-icon">&#129514;</div>'
            +       '<span>Test Platform <small style="opacity:0.6;font-size:0.7em;">v1.3.0</small></span>'
            +     '</div>'
            +   '</div>'
            +   '<nav class="sidebar-nav">'
            +     section("Genel",
                    item("index",     "&#128202;", "Dashboard")
                    + item("workspace","&#128188;", "Workspace")
                  )
            +     section("Test",
                    item("web-test",     "&#127760;", "Web Test")
                    + item("mobile-test","&#128242;", "Mobil Test")
                    + item("desktop-test","&#128421;","Desktop Test")
                  )
            +     section("AI Araçlar",
                    item("ai-generator",   "&#129302;", "AI Test Generator")
                    + item("java-generator","&#9749;",  "Java Generator")
                    + item("bdd-generator","&#129405;", "BDD Generator")
                    + item("test-history", "&#128203;", "Test Geçmişi")
                  )
            +     adminBlock
            +   '</nav>'
            +   '<div class="sidebar-footer">'
            +     '<div class="user-info">'
            +       '<div class="user-avatar">' + initials + '</div>'
            +       '<div class="user-details">'
            +         '<div class="user-name">'  + userName + '</div>'
            +         '<div class="user-role">'  + userRole + '</div>'
            +       '</div>'
            +       '<button class="sidebar-logout-btn" onclick="Auth.logout();" title="Çıkış Yap">&#128682;</button>'
            +     '</div>'
            +   '</div>'
            + '</aside>';

        container.innerHTML = html;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectSidebar);
    } else {
        injectSidebar();
    }

    window.Sidebar = { reload: injectSidebar };
})();
