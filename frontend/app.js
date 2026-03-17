const API_BASE = '/api';
const GOOGLE_CLIENT_ID = window.GOOGLE_CLIENT_ID || '963099562668-j8tqno3ldptc4hb0d1u2kk9chodp49t2.apps.googleusercontent.com';

let allEvents = [];
let currentTab = 'all';
let publicFilter = 'doerr';
let calendar;

function isPersonalMode() {
    return AUTH.isSignedIn();
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();

    AUTH.init((user) => {
        switchMode();
    });

    if (GOOGLE_CLIENT_ID) {
        AUTH.renderButton('google-signin-btn', GOOGLE_CLIENT_ID);
    }

    setupEventListeners();

    const init = isPersonalMode()
        ? fetchPreferences().then(() => { initCalendar(); fetchEvents(); })
        : Promise.resolve().then(() => { initCalendar(); fetchEvents(); });

    setInterval(fetchEvents, 15 * 60 * 1000);
});

function switchMode() {
    const personal = isPersonalMode();

    document.getElementById('sidebar').style.display = personal ? '' : 'none';
    document.getElementById('public-header').style.display = personal ? 'none' : '';
    document.getElementById('personal-header').style.display = personal ? '' : 'none';
    document.getElementById('public-tabs').style.display = personal ? 'none' : 'flex';
    document.getElementById('color-legend').style.display = personal ? 'none' : '';
    document.getElementById('main-content').style.maxWidth = personal ? '' : '1200px';
    document.getElementById('main-content').style.margin = personal ? '' : '0 auto';

    if (personal) {
        AUTH.renderProfile('auth-profile-sidebar');
        document.getElementById('google-signin-btn').style.display = 'none';
        fetchPreferences().then(() => fetchEvents());
    } else {
        AUTH.renderProfile('auth-profile');
        document.getElementById('google-signin-btn').style.display = 'block';
    }
}

function initTheme() {
    const themeToggle = document.getElementById('theme-toggle');
    const savedTheme = localStorage.getItem('theme') || 'light';
    if (savedTheme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        if (themeToggle) themeToggle.checked = true;
    }
    if (themeToggle) {
        themeToggle.addEventListener('change', (e) => {
            const theme = e.target.checked ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
        });
    }
}

function initCalendar() {
    const calendarEl = document.getElementById('calendar');
    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridDay',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        dayMaxEvents: 2,
        eventMaxStack: 2,
        height: 'auto',
        slotMinTime: '08:00:00',
        slotMaxTime: '21:00:00',
        expandRows: true,
        allDaySlot: false,
        slotEventOverlap: false,
        views: {
            timeGridDay: { dayHeaderFormat: { weekday: 'long', month: 'long', day: 'numeric' } },
            timeGridWeek: { dayHeaderFormat: { weekday: 'short', month: 'short', day: 'numeric' } },
            dayGridMonth: { dayHeaderFormat: { weekday: 'short' } }
        },
        eventDidMount: function (info) {
            const cls = info.event.classNames || [];
            let bg, border, txt;
            if (cls.includes('fc-evt-gsb')) {
                bg = '#c4d8e8'; border = '#9bbdd4'; txt = '#2a5070';
            } else if (cls.includes('fc-evt-doerr')) {
                bg = '#c4e0ca'; border = '#98c8a0'; txt = '#2a5030';
            } else if (cls.includes('fc-evt-saved')) {
                bg = '#8c1515'; border = '#6a1010'; txt = '#ffffff';
            } else {
                bg = '#e8c4c4'; border = '#b07070'; txt = '#4a0a0a';
            }
            info.el.style.setProperty('background-color', bg, 'important');
            info.el.style.setProperty('border-color', border, 'important');
            info.el.style.setProperty('color', txt, 'important');
            info.el.setAttribute('title', info.event.title);
            info.el.style.cursor = 'pointer';
            info.el.querySelectorAll('*').forEach(child => {
                child.style.setProperty('color', txt, 'important');
                child.style.setProperty('background', 'transparent', 'important');
            });
        },
        navLinks: true,
        navLinkDayClick: function (date) { calendar.changeView('timeGridDay', date); },
        eventClick: function (info) {
            info.jsEvent.preventDefault();
            if (info.event.url) window.open(info.event.url, '_blank');
        },
        datesSet: function (dateInfo) {
            window.currentCalStart = dateInfo.start;
            window.currentCalEnd = dateInfo.end;
            const fcTitle = document.querySelector('.fc-toolbar-title');
            if (fcTitle) {
                const viewType = dateInfo.view.type;
                if (viewType === 'timeGridDay') {
                    fcTitle.textContent = dateInfo.start.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
                } else if (viewType === 'timeGridWeek') {
                    const ws = dateInfo.start;
                    const we = new Date(dateInfo.end.getTime() - 86400000);
                    fcTitle.textContent = `${ws.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${we.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
                } else if (viewType === 'dayGridMonth') {
                    const mid = new Date((dateInfo.start.getTime() + dateInfo.end.getTime()) / 2);
                    fcTitle.textContent = mid.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
                }
            }
            const mapHeader = document.querySelector('.map-header');
            if (mapHeader) mapHeader.style.display = 'none';
            filterFeedByDate();
        }
    });
    calendar.render();
}

function setupEventListeners() {
    // Chip filters (personal mode)
    document.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const isAll = chip.dataset.value === "All";
            const siblings = chip.parentElement.querySelectorAll('.chip');
            if (isAll) {
                siblings.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
            } else {
                const allChip = chip.parentElement.querySelector('[data-value="All"]');
                if (allChip) allChip.classList.remove('active');
                chip.classList.toggle('active');
                if (!chip.parentElement.querySelector('.chip.active')) {
                    if (allChip) allChip.classList.add('active');
                }
            }
            savePreferencesAndRefresh();
        });
    });

    // Personal mode tabs
    document.getElementById('tab-all-events')?.addEventListener('click', (e) => {
        document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        currentTab = 'all';
        displayEvents(allEvents);
    });
    document.getElementById('tab-interested')?.addEventListener('click', (e) => {
        document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        currentTab = 'interested';
        displayEvents(allEvents);
    });

    // Public mode tabs
    document.getElementById('filter-doerr')?.addEventListener('click', (e) => {
        document.querySelectorAll('#public-tabs .view-tab').forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        publicFilter = 'doerr';
        displayEvents(allEvents);
    });
    document.getElementById('filter-all')?.addEventListener('click', (e) => {
        document.querySelectorAll('#public-tabs .view-tab').forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        publicFilter = 'all';
        displayEvents(allEvents);
    });

    document.getElementById('save-preferences-btn')?.addEventListener('click', () => savePreferencesAndRefresh());

    // Nav buttons
    const navButtons = {
        'next-week-btn': () => {
            const nextMon = new Date();
            nextMon.setDate(nextMon.getDate() + (7 - nextMon.getDay() + 1) % 7 || 7);
            calendar.changeView('timeGridWeek', nextMon);
        },
        'this-month-btn': () => calendar.changeView('dayGridMonth', new Date()),
        'next-month-btn': () => {
            const nm = new Date();
            nm.setMonth(nm.getMonth() + 1);
            calendar.changeView('dayGridMonth', nm);
        }
    };
    Object.keys(navButtons).forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', navButtons[id]);
    });
}

// ---------- Data Fetching ----------

async function fetchPreferences() {
    try {
        const res = await fetch(`${API_BASE}/preferences`, { headers: AUTH.getHeaders() });
        const prefs = await res.json();
        window.userPreferences = prefs;
        const topicEl = document.getElementById('topic-description');
        if (topicEl) topicEl.value = prefs.topics || "";

        function restoreChips(category, values) {
            document.querySelectorAll(`.chip[data-category="${category}"]`).forEach(c => c.classList.remove('active'));
            if (!values || values.length === 0 || values.includes('All')) {
                const all = document.querySelector(`.chip[data-category="${category}"][data-value="All"]`);
                if (all) all.classList.add('active');
            } else {
                values.forEach(v => {
                    const chip = document.querySelector(`.chip[data-category="${category}"][data-value="${v}"]`);
                    if (chip) chip.classList.add('active');
                });
            }
        }
        restoreChips('type', prefs.types);
        restoreChips('location', prefs.locations);
        restoreChips('sponsor', prefs.sponsors);
        restoreChips('perks', prefs.perks);
        restoreChips('formats', prefs.formats);
    } catch (e) { console.error("Error fetching prefs", e); }
}

async function savePreferencesAndRefresh() {
    const topicEl = document.getElementById('topic-description');
    const topics = topicEl ? topicEl.value : '';
    const getActive = (cat) => Array.from(document.querySelectorAll(`.chip.active[data-category="${cat}"]`)).map(c => c.dataset.value);
    try {
        const res = await fetch(`${API_BASE}/preferences`, {
            method: 'POST',
            headers: AUTH.getHeaders(),
            body: JSON.stringify({ topics, types: getActive('type'), locations: getActive('location'), sponsors: getActive('sponsor'), perks: getActive('perks'), formats: getActive('formats') })
        });
        window.userPreferences = await res.json();
        fetchEvents();
    } catch (e) { console.error(e); }
}

async function fetchEvents() {
    try {
        const endpoint = isPersonalMode() ? '/events' : '/events/public';
        const headers = isPersonalMode() ? AUTH.getHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`${API_BASE}${endpoint}`, { headers });
        allEvents = await res.json();
        displayEvents(allEvents);
    } catch (e) { console.error(e); }
}

// ---------- Display ----------

function displayEvents(events) {
    const personal = isPersonalMode();
    const interestedLookup = window.userPreferences?.interested_events || [];

    let activeEvents;
    if (personal) {
        activeEvents = events.filter(e => currentTab === 'all' || interestedLookup.includes(e.id));
    } else {
        activeEvents = publicFilter === 'doerr' ? events.filter(e => e.is_doerr) : events;
    }

    if (calendar) {
        calendar.removeAllEvents();
        const now = new Date();
        const calEvents = activeEvents.filter(e => {
            if (e.is_recurring) return false;
            if (e.time && new Date(e.time) < now) return false;
            return true;
        });
        calendar.addEventSource(calEvents.map(e => {
            let calClass = 'fc-evt-default';
            if (personal && interestedLookup.includes(e.id)) {
                calClass = 'fc-evt-saved';
            } else if (e.is_gsb) {
                calClass = 'fc-evt-gsb';
            } else if (e.is_doerr) {
                calClass = 'fc-evt-doerr';
            }
            return { id: e.id, title: e.title, start: e.time, end: e.end_time, url: e.url, classNames: [calClass] };
        }));
        filterFeedByDate();
    }
}

function filterFeedByDate() {
    const feed = document.getElementById('event-feed');
    feed.innerHTML = '';
    if (!window.currentCalStart || !allEvents.length) return;

    const personal = isPersonalMode();
    const interestedLookup = window.userPreferences?.interested_events || [];
    const calendarLookup = window.userPreferences?.added_to_calendar || [];

    let sourceEvents;
    if (personal) {
        sourceEvents = currentTab === 'interested' ? allEvents.filter(e => interestedLookup.includes(e.id)) : allEvents;
    } else {
        sourceEvents = publicFilter === 'doerr' ? allEvents.filter(e => e.is_doerr) : allEvents;
    }

    const rangeStart = new Date(window.currentCalStart);
    const rangeEnd = new Date(window.currentCalEnd);
    const feedNow = new Date();

    // Non-recurring events in range
    let nonRecurring = sourceEvents.filter(e => {
        if (!e.time || e.is_recurring) return false;
        const d = new Date(e.time);
        if (d < feedNow) return false;
        return d >= rangeStart && d < rangeEnd;
    });

    // Recurring events in range (shown at the bottom)
    let recurring = sourceEvents.filter(e => {
        if (!e.time || !e.is_recurring) return false;
        const d = new Date(e.time);
        if (d < feedNow) return false;
        return d >= rangeStart && d < rangeEnd;
    });

    let visibleEvents = [...nonRecurring, ...recurring];

    if (!visibleEvents.length) {
        const viewType = calendar?.view?.type;
        if (viewType === 'timeGridDay') {
            visibleEvents = sourceEvents
                .filter(e => e.time && !e.is_recurring && new Date(e.time) >= feedNow)
                .slice(0, 5);
            if (visibleEvents.length) {
                feed.innerHTML = '<div class="loading-state"><p>No events on this day. Showing upcoming:</p></div>';
            } else {
                feed.innerHTML = '<div class="loading-state"><p>No events found in this range.</p></div>';
                return;
            }
        } else {
            feed.innerHTML = '<div class="loading-state"><p>No events found in this range.</p></div>';
            return;
        }
    }

    visibleEvents.forEach(event => {
        const isInterested = interestedLookup.includes(event.id);
        const isOnCalendar = calendarLookup.includes(event.id);

        const title = encodeURIComponent(event.title);
        const desc = encodeURIComponent(event.description || "");
        const loc = encodeURIComponent(event.location_name || "Stanford Campus");

        function toGoogleDate(isoStr) {
            if (!isoStr) return "";
            const d = new Date(isoStr);
            if (isNaN(d)) return "";
            return d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
        }
        const gStart = toGoogleDate(event.time);
        const gEnd = toGoogleDate(event.end_time) || gStart;
        const googleUrl = `https://www.google.com/calendar/render?action=TEMPLATE&text=${title}&details=${desc}&location=${loc}&dates=${gStart}/${gEnd}`;
        const outlookUrl = `https://outlook.office.com/calendar/0/deeplink/compose?subject=${title}&body=${desc}&location=${loc}&startdt=${event.time || ""}&enddt=${event.end_time || event.time || ""}`;

        let cardAccent = '';
        if (event.is_gsb) cardAccent = 'card-gsb';
        else if (event.is_doerr) cardAccent = 'card-doerr';

        const card = document.createElement('div');
        card.id = `event-${event.id}`;
        card.className = `event-card ${cardAccent}`;

        // Build card controls (personal mode only)
        const controls = personal ? `
            <div class="card-controls">
                <button class="not-interested-btn" data-tooltip="Hide similar events for 3 months" onclick="notInterestedEvent(${event.id}, this)">🚫</button>
                <button class="dislike-btn" data-tooltip="Show less like this" onclick="dislikeEvent(${event.id}, this)">👎</button>
                <button class="hide-btn" data-tooltip="Hide this event" onclick="hideEvent(${event.id}, this)">✕</button>
            </div>` : '';

        // Perks badges (personal mode only)
        const perks = personal ? `
            <span class="perks-badges">
                ${event.has_free_food ? '<span class="perk-badge" data-tooltip="Free food/refreshments">🍕</span>' : ''}
                ${event.has_merch ? '<span class="perk-badge" data-tooltip="Free swag/merch">🎁</span>' : ''}
            </span>` : '';

        // School label (public mode)
        const schoolLabel = !personal ? (
            (event.is_doerr ? '<span style="font-size:0.75rem;color:#2a8040;font-weight:600">Doerr School</span>' : '') +
            (event.is_gsb ? '<span style="font-size:0.75rem;color:#2a6da8;font-weight:600">GSB</span>' : '')
        ) : '';

        // Action buttons
        let actions;
        if (personal) {
            actions = `
                <button class="btn-interested ${isInterested ? 'added' : ''}" onclick="markInterested(${event.id}, this)">
                    ${isInterested ? 'Saved ✓' : 'Save Event'}
                </button>
                <div class="dropdown">
                    <button class="dropbtn secondary-btn" onclick="toggleCalendarDropdown(${event.id}, this)">
                        ${isOnCalendar ? 'Added to Calendar ✓' : 'Add to Calendar ▾'}
                    </button>
                    <div class="dropdown-content">
                        <a href="${googleUrl}" target="_blank" onclick="markCalendarAdded(${event.id})">Google Calendar</a>
                        <a href="${outlookUrl}" target="_blank" onclick="markCalendarAdded(${event.id})">Outlook / Office 365</a>
                        <a href="${event.url}" target="_blank" onclick="markCalendarAdded(${event.id})">iCal / Apple (Localist)</a>
                    </div>
                </div>`;
        } else {
            actions = `
                <a href="${event.url}" target="_blank" class="btn-interested" style="text-decoration:none;text-align:center">View Details</a>
                <div class="dropdown">
                    <button class="dropbtn secondary-btn" onclick="toggleCalendarDropdown(${event.id}, this)">Add to Calendar ▾</button>
                    <div class="dropdown-content">
                        <a href="${googleUrl}" target="_blank">Google Calendar</a>
                        <a href="${outlookUrl}" target="_blank">Outlook / Office 365</a>
                        <a href="${event.url}" target="_blank">iCal / Apple (Localist)</a>
                    </div>
                </div>`;
        }

        card.innerHTML = `
            ${controls}
            <div class="event-meta-top">
                <span class="event-type">${event.type || 'Event'}</span>
                ${perks}
                ${schoolLabel}
            </div>
            <h3 class="event-title"><a href="${event.url}" target="_blank">${event.title}</a></h3>
            <p class="event-desc">${event.description || ''}</p>
            ${event.is_registration ? '<div style="margin-bottom:1rem"><span class="reg-badge">Registration Required</span></div>' : ''}
            <div class="event-details">
                <div class="detail-row">📅 ${new Date(event.time).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</div>
                <div class="detail-row">📍 ${event.location_name || 'Campus'}</div>
            </div>
            <div class="card-actions">${actions}</div>
        `;
        feed.appendChild(card);
    });
}

// ---------- Personal Mode Actions ----------

async function hideEvent(eventId, btn) {
    const card = btn.closest('.event-card');
    card.style.opacity = '0.3';
    try {
        await fetch(`${API_BASE}/hide`, { method: 'POST', headers: AUTH.getHeaders(), body: JSON.stringify({ event_id: eventId, is_hidden: true }) });
        allEvents = allEvents.filter(e => e.id !== eventId);
        card.remove();
        displayEvents(allEvents);
    } catch (e) { console.error(e); card.style.opacity = '1'; }
}

async function dislikeEvent(eventId, btn) {
    const card = btn.closest('.event-card');
    card.style.opacity = '0.3';
    try {
        await fetch(`${API_BASE}/dislike`, { method: 'POST', headers: AUTH.getHeaders(), body: JSON.stringify({ event_id: eventId }) });
        allEvents = allEvents.filter(e => e.id !== eventId);
        card.remove();
    } catch (e) { console.error(e); card.style.opacity = '1'; }
}

async function notInterestedEvent(eventId, btn) {
    const card = btn.closest('.event-card');
    card.style.opacity = '0.3';
    try {
        await fetch(`${API_BASE}/not-interested`, { method: 'POST', headers: AUTH.getHeaders(), body: JSON.stringify({ event_id: eventId, months: 3 }) });
        allEvents = allEvents.filter(e => e.id !== eventId);
        card.remove();
        displayEvents(allEvents);
    } catch (e) { console.error(e); card.style.opacity = '1'; }
}

async function markInterested(eventId, btn) {
    const isAdding = !btn.classList.contains('added');
    try {
        await fetch(`${API_BASE}/interested`, { method: 'POST', headers: AUTH.getHeaders(), body: JSON.stringify({ event_id: eventId, is_interested: isAdding }) });
        if (!window.userPreferences.interested_events) window.userPreferences.interested_events = [];
        if (isAdding) window.userPreferences.interested_events.push(eventId);
        else window.userPreferences.interested_events = window.userPreferences.interested_events.filter(id => id !== eventId);
        displayEvents(allEvents);
    } catch (e) { console.error(e); }
}

async function toggleCalendarDropdown(eventId, btn) {
    const parent = btn.parentElement;
    parent.classList.toggle('open');
    if (parent.classList.contains('open')) {
        setTimeout(() => {
            const closer = (e) => {
                if (!parent.contains(e.target)) {
                    parent.classList.remove('open');
                    document.removeEventListener('click', closer);
                }
            };
            document.addEventListener('click', closer);
        }, 10);
    }
}

async function markCalendarAdded(eventId) {
    try {
        await fetch(`${API_BASE}/calendar_added`, { method: 'POST', headers: AUTH.getHeaders(), body: JSON.stringify({ event_id: eventId }) });
        if (!window.userPreferences.added_to_calendar) window.userPreferences.added_to_calendar = [];
        if (!window.userPreferences.added_to_calendar.includes(eventId)) {
            window.userPreferences.added_to_calendar.push(eventId);
        }
        displayEvents(allEvents);
    } catch (e) { console.error(e); }
}
