/* ============================================
   Test Otomasyon Platformu - Ana JavaScript
   (FIXED: [object Object] hatası giderildi)
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
        let url = `${API_URL}${endpoint}`;
        const token = Auth.getToken();
        
        // Cache Buster
        if (options.method === 'GET' || !options.method) {
            const separator = url.includes('?') ? '&' : '?';
            url = `${url}${separator}_t=${new Date().getTime()}`;
        }
        
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
        
        try {
            const response = await fetch(url, config);
            
            if (response.status === 401) {
                Auth.logout();
                throw new Error('Oturum süresi doldu');
            }
            
            if (response.status === 204) return { success: true };

            const data = await response.json();
            
            if (!response.ok) {
                // HATA DUZELTME: Nesne gelirse stringe cevir
                let errorMsg = data.detail || 'Bir hata oluştu';
                if (typeof errorMsg === 'object') {
                    // Pydantic validation hatası ise detaylandır
                    if (Array.isArray(errorMsg)) {
                        errorMsg = errorMsg.map(e => `${e.loc[1]}: ${e.msg}`).join(', ');
                    } else {
                        errorMsg = JSON.stringify(errorMsg);
                    }
                }
                throw new Error(errorMsg);
            }
            
            return data;
        } catch (error) {
            console.error("API Error:", error);
            throw error;
        }
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
    update(id, data) { return API.put(`/devices/${id}`, data); }, // PUT eklendi
    delete(id) { return API.delete(`/devices/${id}`); },
    lock(id) { return API.post(`/devices/${id}/lock`, {}); },
    unlock(id) { return API.post(`/devices/${id}/unlock`, {}); }
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

// Theme, Toast, Modal, Utils, UI (Aynen Kalacak)
const Theme = {
    get() { return Storage.get('theme') || 'light'; },
    set(theme) {
        Storage.set('theme', theme);
        document.body.setAttribute('data-theme', theme);
        this.updateIcon();
    },
    toggle() { this.set(this.get() === 'light' ? 'dark' : 'light'); },
    init() { document.body.setAttribute('data-theme', this.get()); this.updateIcon(); },
    updateIcon() { const btn = document.querySelector('.theme-toggle'); if (btn) btn.textContent = this.get() === 'light' ? '🌙' : '☀️'; }
};

const Toast = {
    container: null,
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            Object.assign(this.container.style, {
                position: 'fixed', bottom: '20px', right: '20px', zIndex: '9999', 
                display: 'flex', flexDirection: 'column', gap: '10px'
            });
            document.body.appendChild(this.container);
        }
    },
    show(message, type = 'success', duration = 3000) {
        this.init();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        let icon = type === 'success' ? 'check_circle' : type === 'error' ? 'error' : 'info';
        toast.innerHTML = `<span class="material-icons-round" style="font-size:1.2rem; margin-right:8px;">${icon}</span><span>${message}</span>`;
        Object.assign(toast.style, {
            background: type === 'success' ? '#10B981' : type === 'error' ? '#EF4444' : '#3B82F6',
            color: 'white', padding: '12px 16px', borderRadius: '8px', 
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)', display: 'flex', alignItems: 'center',
            minWidth: '250px', fontSize: '0.9rem', fontWeight: '500', animation: 'slideIn 0.3s ease-out'
        });
        this.container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0'; toast.style.transform = 'translateX(20px)'; toast.style.transition = 'all 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },
    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error'); },
    info(msg) { this.show(msg, 'info'); }
};

const Modal = {
    show(id) { const m = document.getElementById(id); if (m) m.style.display = 'flex'; },
    hide(id) { const m = document.getElementById(id); if (m) m.style.display = 'none'; }
};

const Utils = {
    formatDate(dateString) {
        if(!dateString) return '-';
        return new Date(dateString).toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
    formatRelativeTime(dateString) {
        const diff = new Date() - new Date(dateString);
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);
        if (minutes < 1) return 'Az önce';
        if (minutes < 60) return `${minutes} dk önce`;
        if (hours < 24) return `${hours} saat önce`;
        if (days < 7) return `${days} gün önce`;
        return this.formatDate(dateString);
    },
    getInitials(name) { return !name ? '?' : name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2); },
    escapeHtml(text) { if (!text) return ''; const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
};

const UI = {
    renderUserInfo() {
        const user = Auth.getUser();
        if (!user) return;
        document.querySelectorAll('.user-name').forEach(el => el.textContent = user.full_name || user.username);
        document.querySelectorAll('.user-avatar').forEach(el => el.textContent = Utils.getInitials(user.full_name || user.username));
        document.querySelectorAll('.user-role').forEach(el => el.textContent = user.role === 'admin' ? 'Yönetici' : 'Kullanıcı');
    }
};

document.addEventListener('DOMContentLoaded', () => { Theme.init(); });