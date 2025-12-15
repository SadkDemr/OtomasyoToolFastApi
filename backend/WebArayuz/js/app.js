/* ============================================
   Test Otomasyon Platformu - Ana JavaScript
   ============================================ */

const API_URL = 'http://localhost:8000/api';

// Storage
const Storage = {
    get(key) {
        try { return JSON.parse(localStorage.getItem(key)); }
        catch { return localStorage.getItem(key); }
    },
    set(key, value) {
        localStorage.setItem(key, typeof value === 'object' ? JSON.stringify(value) : value);
    },
    remove(key) { localStorage.removeItem(key); }
};

// Auth
const Auth = {
    getToken() { return Storage.get('token'); },
    setToken(token) { Storage.set('token', token); },
    getUser() { return Storage.get('user'); },
    setUser(user) { Storage.set('user', user); },
    isLoggedIn() { return !!this.getToken(); },
    logout() {
        Storage.remove('token');
        Storage.remove('user');
        window.location.href = 'login.html';
    },
    checkAuth() {
        if (!this.isLoggedIn()) {
            window.location.href = 'login.html';
            return false;
        }
        return true;
    }
};

// API
const API = {
    async request(endpoint, options = {}) {
        const url = `${API_URL}${endpoint}`;
        const token = Auth.getToken();
        
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...(token && { 'Authorization': `Bearer ${token}` }),
                ...options.headers
            },
            ...options
        };
        
        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }
        
        const response = await fetch(url, config);
        
        if (response.status === 401) {
            Auth.logout();
            throw new Error('Oturum suresi doldu');
        }
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Bir hata olustu');
        }
        
        return data;
    },
    get(endpoint) { return this.request(endpoint, { method: 'GET' }); },
    post(endpoint, data) { return this.request(endpoint, { method: 'POST', body: data }); },
    put(endpoint, data) { return this.request(endpoint, { method: 'PUT', body: data }); },
    delete(endpoint) { return this.request(endpoint, { method: 'DELETE' }); }
};

// Auth API
const AuthAPI = {
    async login(username, password) {
        const data = await API.post('/auth/login', { username, password });
        Auth.setToken(data.access_token);
        Auth.setUser(data.user);
        return data;
    },
    async register(username, email, password, fullName) {
        const data = await API.post('/auth/register', { username, email, password, full_name: fullName });
        Auth.setToken(data.access_token);
        Auth.setUser(data.user);
        return data;
    }
};

// Scenarios API
const ScenariosAPI = {
    list(type = null) {
        const endpoint = type ? `/scenarios?type=${type}` : '/scenarios';
        return API.get(endpoint);
    },
    get(id) { return API.get(`/scenarios/${id}`); },
    create(data) { return API.post('/scenarios', data); },
    update(id, data) { return API.put(`/scenarios/${id}`, data); },
    delete(id) { return API.delete(`/scenarios/${id}`); },
    getStats() { return API.get('/scenarios/stats'); }
};

// Devices API
const DevicesAPI = {
    list(type = null) {
        const endpoint = type ? `/devices?type=${type}` : '/devices';
        return API.get(endpoint);
    },
    get(id) { return API.get(`/devices/${id}`); },
    create(data) { return API.post('/devices', data); },
    update(id, data) { return API.put(`/devices/${id}`, data); },
    delete(id) { return API.delete(`/devices/${id}`); },
    lock(id) { return API.post(`/devices/${id}/lock`); },
    unlock(id) { return API.post(`/devices/${id}/unlock`); }
};

// Test API
const TestAPI = {
    runWebTest(data) { return API.post('/web/run-test', data); },
    runMobileTest(data) { return API.post('/mobile/run-test', data); },
    parseNatural(text, type = 'web') {
        const endpoint = type === 'web' ? '/web/parse' : '/mobile/parse';
        return API.post(`${endpoint}?text=${encodeURIComponent(text)}`);
    }
};

// Theme
const Theme = {
    get() { return Storage.get('theme') || 'light'; },
    set(theme) {
        Storage.set('theme', theme);
        document.documentElement.setAttribute('data-theme', theme);
        this.updateIcon();
    },
    toggle() {
        this.set(this.get() === 'light' ? 'dark' : 'light');
    },
    init() {
        document.documentElement.setAttribute('data-theme', this.get());
        this.updateIcon();
    },
    updateIcon() {
        const btn = document.querySelector('.theme-toggle');
        if (btn) btn.textContent = this.get() === 'light' ? '🌙' : '☀️';
    }
};

// Toast
const Toast = {
    container: null,
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    },
    show(message, type = 'success', duration = 3000) {
        this.init();
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${type === 'success' ? '✓' : '✕'}</span>
            <span class="toast-message">${message}</span>
        `;
        this.container.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },
    success(message) { this.show(message, 'success'); },
    error(message) { this.show(message, 'error'); }
};

// Modal
const Modal = {
    show(id) {
        const modal = document.getElementById(id);
        if (modal) modal.classList.add('active');
    },
    hide(id) {
        const modal = document.getElementById(id);
        if (modal) modal.classList.remove('active');
    }
};

// Utils
const Utils = {
    formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('tr-TR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    },
    formatRelativeTime(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);
        
        if (minutes < 1) return 'Az once';
        if (minutes < 60) return `${minutes} dk once`;
        if (hours < 24) return `${hours} saat once`;
        if (days < 7) return `${days} gun once`;
        return this.formatDate(dateString);
    },
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
    getInitials(name) {
        if (!name) return '?';
        return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    }
};

// UI
const UI = {
    renderUserInfo() {
        const user = Auth.getUser();
        if (!user) return;
        const container = document.querySelector('.user-info');
        if (container) {
            container.innerHTML = `
                <div class="user-avatar">${Utils.getInitials(user.full_name || user.username)}</div>
                <div class="user-details">
                    <div class="user-name">${user.full_name || user.username}</div>
                    <div class="user-role">${user.role === 'admin' ? 'Yonetici' : 'Kullanici'}</div>
                </div>
            `;
        }
    }
};

// Sidebar Component
function renderSidebar(activePage) {
    return `
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <div class="logo-icon">🧪</div>
                    <span>Test Platform</span>
                </div>
            </div>
            
            <nav class="sidebar-nav">
                <div class="nav-section">
                    <div class="nav-section-title">Ana Menu</div>
                    <a href="index.html" class="nav-item ${activePage === 'dashboard' ? 'active' : ''}">
                        <span class="nav-item-icon">📊</span>
                        <span>Dashboard</span>
                    </a>
                    <a href="scenarios.html" class="nav-item ${activePage === 'scenarios' ? 'active' : ''}">
                        <span class="nav-item-icon">📝</span>
                        <span>Senaryolar</span>
                    </a>
                </div>
                
                <div class="nav-section">
                    <div class="nav-section-title">Test Turleri</div>
                    <a href="web-test.html" class="nav-item ${activePage === 'web-test' ? 'active' : ''}">
                        <span class="nav-item-icon">🌐</span>
                        <span>Web Test</span>
                    </a>
                    <a href="mobile-test.html" class="nav-item ${activePage === 'mobile-test' ? 'active' : ''}">
                        <span class="nav-item-icon">📲</span>
                        <span>Mobil Test</span>
                    </a>
                </div>
            </nav>
            
            <div class="sidebar-footer">
                <div class="user-info" onclick="if(confirm('Cikis yapmak istiyor musunuz?')) Auth.logout();">
                    <div class="user-avatar">?</div>
                    <div class="user-details">
                        <div class="user-name">Yukleniyor...</div>
                        <div class="user-role">-</div>
                    </div>
                </div>
            </div>
        </aside>
    `;
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
});
