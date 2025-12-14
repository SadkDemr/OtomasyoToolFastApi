/* ============================================
   Test Otomasyon Platformu - Ana JavaScript
   API, Auth, Theme, Utils
   ============================================ */

// API Base URL
const API_URL = 'http://localhost:8000/api';

// ============================================
// Storage & Auth
// ============================================

const Storage = {
    get(key) {
        try {
            return JSON.parse(localStorage.getItem(key));
        } catch {
            return localStorage.getItem(key);
        }
    },
    
    set(key, value) {
        localStorage.setItem(key, typeof value === 'object' ? JSON.stringify(value) : value);
    },
    
    remove(key) {
        localStorage.removeItem(key);
    },
    
    clear() {
        localStorage.clear();
    }
};

const Auth = {
    getToken() {
        return Storage.get('token');
    },
    
    setToken(token) {
        Storage.set('token', token);
    },
    
    getUser() {
        return Storage.get('user');
    },
    
    setUser(user) {
        Storage.set('user', user);
    },
    
    isLoggedIn() {
        return !!this.getToken();
    },
    
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

// ============================================
// API Client
// ============================================

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
        
        try {
            const response = await fetch(url, config);
            
            // Token expired
            if (response.status === 401) {
                Auth.logout();
                throw new Error('Oturum süresi doldu');
            }
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || 'Bir hata oluştu');
            }
            
            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },
    
    get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },
    
    post(endpoint, data) {
        return this.request(endpoint, { method: 'POST', body: data });
    },
    
    put(endpoint, data) {
        return this.request(endpoint, { method: 'PUT', body: data });
    },
    
    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
};

// ============================================
// Auth API
// ============================================

const AuthAPI = {
    async login(username, password) {
        const data = await API.post('/auth/login', { username, password });
        Auth.setToken(data.access_token);
        Auth.setUser(data.user);
        return data;
    },
    
    async register(username, email, password, fullName) {
        const data = await API.post('/auth/register', {
            username,
            email,
            password,
            full_name: fullName
        });
        Auth.setToken(data.access_token);
        Auth.setUser(data.user);
        return data;
    },
    
    async getMe() {
        return API.get('/auth/me');
    }
};

// ============================================
// Scenarios API
// ============================================

const ScenariosAPI = {
    async list(type = null) {
        const endpoint = type ? `/scenarios?type=${type}` : '/scenarios';
        return API.get(endpoint);
    },
    
    async get(id) {
        return API.get(`/scenarios/${id}`);
    },
    
    async create(data) {
        return API.post('/scenarios', data);
    },
    
    async update(id, data) {
        return API.put(`/scenarios/${id}`, data);
    },
    
    async delete(id) {
        return API.delete(`/scenarios/${id}`);
    },
    
    async duplicate(id, newName = null) {
        const endpoint = newName 
            ? `/scenarios/${id}/duplicate?new_name=${encodeURIComponent(newName)}`
            : `/scenarios/${id}/duplicate`;
        return API.post(endpoint);
    },
    
    async getStats() {
        return API.get('/scenarios/stats');
    }
};

// ============================================
// Devices API
// ============================================

const DevicesAPI = {
    async list(type = null) {
        const endpoint = type ? `/devices?type=${type}` : '/devices';
        return API.get(endpoint);
    },
    
    async get(id) {
        return API.get(`/devices/${id}`);
    },
    
    async create(data) {
        return API.post('/devices', data);
    },
    
    async update(id, data) {
        return API.put(`/devices/${id}`, data);
    },
    
    async delete(id) {
        return API.delete(`/devices/${id}`);
    },
    
    async lock(id) {
        return API.post(`/devices/${id}/lock`);
    },
    
    async unlock(id) {
        return API.post(`/devices/${id}/unlock`);
    },
    
    async getMyDevice() {
        return API.get('/devices/my');
    }
};

// ============================================
// Test API
// ============================================

const TestAPI = {
    async runWebTest(data) {
        return API.post('/web/run-test', data);
    },
    
    async runMobileTest(data) {
        return API.post('/mobile/run-test', data);
    },
    
    async parseNatural(text, type = 'web') {
        const endpoint = type === 'web' ? '/web/parse' : '/mobile/parse';
        return API.post(`${endpoint}?text=${encodeURIComponent(text)}`);
    }
};

// ============================================
// Theme Management
// ============================================

const Theme = {
    get() {
        return Storage.get('theme') || 'light';
    },
    
    set(theme) {
        Storage.set('theme', theme);
        document.documentElement.setAttribute('data-theme', theme);
        this.updateIcon();
    },
    
    toggle() {
        const current = this.get();
        const newTheme = current === 'light' ? 'dark' : 'light';
        this.set(newTheme);
    },
    
    init() {
        const theme = this.get();
        document.documentElement.setAttribute('data-theme', theme);
        this.updateIcon();
    },
    
    updateIcon() {
        const btn = document.querySelector('.theme-toggle');
        if (btn) {
            btn.innerHTML = this.get() === 'light' ? '🌙' : '☀️';
        }
    }
};

// ============================================
// Toast Notifications
// ============================================

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
    
    success(message) {
        this.show(message, 'success');
    },
    
    error(message) {
        this.show(message, 'error');
    }
};

// ============================================
// Modal
// ============================================

const Modal = {
    show(id) {
        const modal = document.getElementById(id);
        if (modal) {
            modal.classList.add('active');
        }
    },
    
    hide(id) {
        const modal = document.getElementById(id);
        if (modal) {
            modal.classList.remove('active');
        }
    },
    
    init() {
        // Close on overlay click
        document.querySelectorAll('.modal-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    overlay.classList.remove('active');
                }
            });
        });
        
        // Close buttons
        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.closest('.modal-overlay').classList.remove('active');
            });
        });
    }
};

// ============================================
// Utilities
// ============================================

const Utils = {
    // Format date
    formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    },
    
    // Format relative time
    formatRelativeTime(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;
        
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);
        
        if (minutes < 1) return 'Az önce';
        if (minutes < 60) return `${minutes} dk önce`;
        if (hours < 24) return `${hours} saat önce`;
        if (days < 7) return `${days} gün önce`;
        
        return this.formatDate(dateString);
    },
    
    // Debounce
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    // Get initials
    getInitials(name) {
        if (!name) return '?';
        return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    },
    
    // Escape HTML
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// ============================================
// UI Components
// ============================================

const UI = {
    // Render user info in sidebar
    renderUserInfo() {
        const user = Auth.getUser();
        if (!user) return;
        
        const container = document.querySelector('.user-info');
        if (container) {
            container.innerHTML = `
                <div class="user-avatar">${Utils.getInitials(user.full_name || user.username)}</div>
                <div class="user-details">
                    <div class="user-name">${user.full_name || user.username}</div>
                    <div class="user-role">${user.role === 'admin' ? 'Yönetici' : 'Kullanıcı'}</div>
                </div>
            `;
        }
    },
    
    // Set active nav item
    setActiveNav(page) {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
            if (item.dataset.page === page) {
                item.classList.add('active');
            }
        });
    },
    
    // Loading state
    setLoading(element, loading) {
        if (loading) {
            element.classList.add('loading');
            element.disabled = true;
        } else {
            element.classList.remove('loading');
            element.disabled = false;
        }
    }
};

// ============================================
// Initialize
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    Modal.init();
    
    // Theme toggle
    const themeBtn = document.querySelector('.theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => Theme.toggle());
    }
    
    // User dropdown / logout
    const userInfo = document.querySelector('.user-info');
    if (userInfo) {
        userInfo.addEventListener('click', () => {
            if (confirm('Çıkış yapmak istiyor musunuz?')) {
                Auth.logout();
            }
        });
    }
});
