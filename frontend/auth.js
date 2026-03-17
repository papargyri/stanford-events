// Auth module — handles Google Sign-In and anonymous fallback
// Include Google's GSI library in your HTML:
// <script src="https://accounts.google.com/gsi/client" async></script>

const AUTH = {
    user: null,
    token: null,
    onLogin: null, // callback after login

    init(onLogin) {
        this.onLogin = onLogin;
        // Check localStorage for existing session
        const saved = localStorage.getItem('stanford_events_auth');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                // Google tokens expire — check if it's an anonymous ID (always valid)
                if (data.type === 'anonymous') {
                    this.user = data.user;
                    this.token = null;
                    if (this.onLogin) this.onLogin(this.user);
                    return;
                }
                // For Google tokens, re-verify on page load
                // Token might be expired but user info is still useful for display
                this.user = data.user;
                this.token = data.token;
                if (this.onLogin) this.onLogin(this.user);
            } catch (e) {
                localStorage.removeItem('stanford_events_auth');
            }
        }
    },

    getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        if (this.token) {
            headers['Authorization'] = 'Bearer ' + this.token;
        } else if (this.user && this.user.id) {
            headers['X-User-ID'] = this.user.id;
        } else {
            // Generate anonymous ID
            let anonId = localStorage.getItem('stanford_events_anon_id');
            if (!anonId) {
                anonId = 'anon_' + Math.random().toString(36).substr(2, 12);
                localStorage.setItem('stanford_events_anon_id', anonId);
            }
            headers['X-User-ID'] = anonId;
        }
        return headers;
    },

    handleGoogleResponse(response) {
        const token = response.credential;
        // Decode JWT payload (base64)
        const payload = JSON.parse(atob(token.split('.')[1]));
        const user = {
            id: payload.sub,
            email: payload.email,
            name: payload.name,
            picture: payload.picture
        };
        this.user = user;
        this.token = token;
        localStorage.setItem('stanford_events_auth', JSON.stringify({
            type: 'google', user: user, token: token
        }));
        if (this.onLogin) this.onLogin(user);
    },

    signOut() {
        this.user = null;
        this.token = null;
        localStorage.removeItem('stanford_events_auth');
        // Keep anonymous ID so preferences persist
        window.location.reload();
    },

    isSignedIn() {
        return this.user && this.user.email;
    },

    renderButton(containerId, clientId) {
        if (!window.google || !window.google.accounts) {
            // GSI not loaded yet, retry
            setTimeout(() => this.renderButton(containerId, clientId), 200);
            return;
        }
        google.accounts.id.initialize({
            client_id: clientId,
            callback: (resp) => this.handleGoogleResponse(resp),
            auto_select: true
        });
        const container = document.getElementById(containerId);
        if (container) {
            google.accounts.id.renderButton(container, {
                theme: 'outline',
                size: 'medium',
                shape: 'pill',
                text: 'signin_with'
            });
        }
    },

    renderProfile(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        if (this.isSignedIn()) {
            container.innerHTML =
                '<div style="display:flex;align-items:center;gap:0.5rem;">' +
                (this.user.picture ? '<img src="' + this.user.picture + '" style="width:28px;height:28px;border-radius:50%">' : '') +
                '<span style="font-size:0.85rem;color:var(--text-primary)">' + (this.user.name || this.user.email) + '</span>' +
                '<button onclick="AUTH.signOut()" style="font-size:0.75rem;padding:0.25rem 0.5rem;border-radius:4px;border:1px solid var(--border);background:var(--card-bg);color:var(--text-secondary);cursor:pointer">Sign out</button>' +
                '</div>';
        }
    }
};
