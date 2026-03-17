from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import re
import os
import sys
import time
import threading
import requests as http_requests
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler

# Add the current directory to sys.path to allow importing scraper
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from scraper import StanfordEventsScraper
from database import get_or_create_user, get_preferences, update_preferences, add_action, remove_action

# ---------- NLP Helpers ----------

def _detect_free_food(text: str) -> bool:
    """Context-aware detection of whether an event offers free food/drinks."""
    strong_phrases = [
        r"free\s+food", r"food\s+provided", r"food\s+will\s+be",
        r"complimentary\s+(food|lunch|dinner|breakfast|refreshments)",
        r"light\s+(refreshments|lunch|breakfast)",
        r"(lunch|dinner|breakfast|refreshments)\s+(provided|served|included|available)",
        r"(catered|catering)", r"reception\s+(to\s+follow|following|after)",
        r"happy\s+hour", r"potluck", r"banquet",
    ]
    for pat in strong_phrases:
        if re.search(pat, text, re.I): return True

    food_words = ["lunch", "dinner", "breakfast", "brunch", "pizza", "tacos", "boba", "coffee", "refreshments"]
    word_pattern = r"\b(" + "|".join(food_words) + r")\b"
    
    negative_context = ["food system", "food security", "food policy", "clinical", "treatment"]
    serving_context = [r"\bprovided\b", r"\bserved\b", r"\bavailable\b", r"\bfree\b"]

    sentences = re.split(r'[.!?\n]+', text)
    for s in sentences:
        s = s.strip().lower()
        if not s: continue
        if re.search(word_pattern, s) and not any(neg in s for neg in negative_context):
            if any(re.search(p, s) for p in serving_context):
                return True
    return False

def _detect_merch(text: str) -> bool:
    """Context-aware detection of whether an event offers merch/swag."""
    strong_phrases = [r"free\s+(t-shirt|swag|merch|sticker)", r"swag\s+bag", r"giveaway"]
    for pat in strong_phrases:
        if re.search(pat, text, re.I): return True
    return False

def _requires_registration(event: dict) -> bool:
    """Detects if an event likely requires registration/RSVP."""
    text = f"{event.get('title','')} {event.get('description','')}".lower()
    strong_keywords = [r"\bregister\b", r"\brsvp\b", r"\bdeadline\b", r"\btickets\b", r"\bsign-up\b"]
    if any(re.search(p, text) for p in strong_keywords):
        if not any(re.search(p, text) for p in [r"no\s+registration\s+required", r"no\s+rsvp"]):
            return True
    return False

def _is_recurring(event: dict) -> bool:
    """Helper to detect if an event is recurring/routine or long-running (e.g. exhibitions spanning weeks)."""
    text = f"{event.get('title','')} {event.get('description','')}".lower()
    recurring_keywords = [r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", r"weekly", r"monthly", r"office\s+hours", r"recurring"]
    if any(re.search(p, text, re.I) for p in recurring_keywords):
        return True
    # Detect long-running events (exhibitions, installations) by checking date span
    try:
        start = event.get("time")
        end = event.get("end_time")
        if start and end:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            if (end_dt - start_dt).days >= 3:  # spans 3+ days = long-running
                return True
    except:
        pass
    # Exhibitions are almost always long-running/recurring
    etype = event.get("type", "")
    if etype == "Exhibition":
        return True
    return False

def _normalize_title(title: str) -> str:
    """Normalize a title for fuzzy matching across recurring instances.
    Strips day names, dates, ordinals, and extra whitespace so that
    'AA Tuesday Meeting' matches 'AA Wednesday Meeting'."""
    t = title.lower().strip()
    # Remove day names
    t = re.sub(r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', '', t)
    # Remove month names + day numbers like "March 16" or "Mar 16th"
    t = re.sub(r'\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b', '', t)
    # Remove standalone numbers and ordinals (16th, 3rd, etc.)
    t = re.sub(r'\b\d+(st|nd|rd|th)?\b', '', t)
    # Remove extra whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def _titles_match(title_a: str, title_b: str) -> bool:
    """Check if two normalized titles are similar enough to be the same recurring event."""
    na, nb = _normalize_title(title_a), _normalize_title(title_b)
    if not na or not nb:
        return False
    # Exact match after normalization
    if na == nb:
        return True
    # One contains the other (handles slight variations)
    if na in nb or nb in na:
        return len(min(na, nb, key=len)) / len(max(na, nb, key=len)) > 0.7
    return False

# ---------- FastAPI & App Config ----------

app = FastAPI(title="Stanford Events API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

@app.get("/")
def read_root():
    """Main page — public by default, personal features unlock after Google Sign-In."""
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/style.css")
def get_css():
    return FileResponse(os.path.join(frontend_path, "style.css"))

@app.get("/app.js")
def get_js():
    return FileResponse(os.path.join(frontend_path, "app.js"))

@app.get("/auth.js")
def get_auth_js():
    return FileResponse(os.path.join(frontend_path, "auth.js"))

scraper = StanfordEventsScraper()
scheduler = BackgroundScheduler()
events_cache = {"last_fetched": 0, "events": []}

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "963099562668-j8tqno3ldptc4hb0d1u2kk9chodp49t2.apps.googleusercontent.com")

def _get_user_id(request: Request) -> str:
    """Extract user ID from request. Supports Google token or anonymous localStorage ID."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        # Verify Google ID token
        try:
            resp = http_requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={token}",
                timeout=5
            )
            if resp.status_code == 200:
                info = resp.json()
                user_id = info.get("sub", "")
                email = info.get("email", "")
                name = info.get("name", "")
                picture = info.get("picture", "")
                get_or_create_user(user_id, email=email, name=name, picture=picture)
                return user_id
        except:
            pass
    # Fallback: anonymous user ID from header
    anon_id = request.headers.get("X-User-ID", "anonymous")
    get_or_create_user(anon_id)
    return anon_id

# ---------- Models ----------

class PreferencesUpdate(BaseModel):
    topics: Optional[str] = None
    types: Optional[List[str]] = None
    locations: Optional[List[str]] = None
    sponsors: Optional[List[str]] = None
    perks: Optional[List[str]] = None
    formats: Optional[List[str]] = None

class HideRequest(BaseModel):
    event_id: int
    is_hidden: bool = True

class CalendarAddedRequest(BaseModel):
    event_id: int

class InterestedRequest(BaseModel):
    event_id: int
    is_interested: bool = True

class DislikeRequest(BaseModel):
    event_id: int

class NotInterestedRequest(BaseModel):
    event_id: int
    months: int = 3  # suppress for this many months

# ---------- Helpers ----------

def fetch_and_cache_events():
    now = time.time()
    if now - events_cache["last_fetched"] > 3600 or not events_cache["events"]:
        events_cache["events"] = scraper.fetch_events(days=60)
        events_cache["last_fetched"] = now
    return events_cache["events"]

def get_personalized_events(all_events, prefs=None):
    try:
        current_time = datetime.now(timezone.utc)
        personalized = []

        if prefs is None:
            prefs = {"topics": "", "types": ["All"], "locations": ["All"], "sponsors": ["All"],
                     "perks": ["All"], "formats": ["All"], "interested_events": [], "added_to_calendar": [],
                     "hidden_events": [], "disliked_topics": [], "disliked_sponsors": [], "not_interested": []}
        hidden_list = prefs.get("hidden_events", [])
        recurring_stats = prefs.get("recurring_hidden_stats", {})

        # Pre-compute: events with duplicate normalized titles are recurring
        from collections import Counter
        title_counts = Counter(_normalize_title(e.get("title", "")) for e in all_events)
        duplicate_titles = {t for t, c in title_counts.items() if c >= 3 and t}
        
        # Build frequency maps for Ranking
        interest_weights = {
            "topics": {}, "sponsors": {}, 
            "hidden_topics": {}, "hidden_sponsors": {},
            "disliked_topics": prefs.get("disliked_topics", []),
            "disliked_sponsors": prefs.get("disliked_sponsors", [])
        }
        
        # Personalization from explicit interest
        for eid in prefs.get("interested_events", []) + prefs.get("added_to_calendar", []):
            weight = 3.0 if eid in prefs.get("added_to_calendar", []) else 1.0
            event = next((e for e in all_events if e.get("id") == eid), None)
            if event:
                for t in event.get("topics", []):
                    tl = t.lower()
                    interest_weights["topics"][tl] = interest_weights["topics"].get(tl, 0) + weight
                gn = str(event.get("group_name", "")).lower()
                if gn: interest_weights["sponsors"][gn] = interest_weights["sponsors"].get(gn, 0) + weight
        
        # Personalization from hidden events
        for eid in hidden_list:
            event = next((e for e in all_events if e.get("id") == eid), None)
            if event:
                for t in event.get("topics", []):
                    interest_weights["hidden_topics"][t.lower()] = interest_weights["hidden_topics"].get(t.lower(), 0) + 1
                gn = str(event.get("group_name", "")).lower()
                if gn: interest_weights["hidden_sponsors"][gn] = interest_weights["hidden_sponsors"].get(gn, 0) + 1

        # Build active not-interested patterns (filter out expired ones)
        ni_patterns = []
        for entry in prefs.get("not_interested", []):
            try:
                expires = datetime.fromisoformat(entry["expires_at"])
                if expires > current_time:
                    ni_patterns.append(entry)
            except:
                ni_patterns.append(entry)  # keep if we can't parse expiry

        for event in all_events:
            event_id = event.get("id")
            if event_id in hidden_list: continue

            # Not Interested: suppress events matching stored title patterns
            event_title = event.get("title", "")
            is_suppressed = any(_titles_match(event_title, p.get("title", "")) for p in ni_patterns)
            if is_suppressed: continue

            # Strike Rule
            if _is_recurring(event):
                slug = f"{event.get('title','')}_{event.get('group_name','')}".lower()
                if recurring_stats.get(slug, 0) >= 3: continue

            title_l = str(event.get("title", "")).lower()
            desc_l = str(event.get("description", "")).lower()
            group_l = str(event.get("group_name", "")).lower()
            url_l = str(event.get("url", "")).lower()
            topic_str = " ".join(event.get("topics", [])).lower()

            # Time check
            try:
                start_dt = datetime.fromisoformat(event.get("time")) if event.get("time") else None
                if start_dt and start_dt + timedelta(hours=4) < current_time: continue
            except: pass

            # Filter: Event Types
            pref_types = prefs.get("types", ["All"])
            if "All" not in pref_types:
                etype_raw = event.get("type", "Event")
                if etype_raw not in pref_types:
                    continue

            # Filter: Location
            pref_locations = prefs.get("locations", ["All"])
            if "All" not in pref_locations:
                loc = str(event.get("location_name", "")).lower()
                is_virtual = any(kw in loc for kw in ["virtual", "online", "zoom", "webinar", "remote"])
                if "Physical" in pref_locations and is_virtual:
                    continue
                if "Virtual" in pref_locations and not is_virtual:
                    continue

            # Filter: Sponsors
            pref_sponsors = prefs.get("sponsors", ["All"])
            if "All" not in pref_sponsors:
                matched = False
                for s in pref_sponsors:
                    sl = s.lower()
                    if sl == "doerr" and ("doerr" in group_l or "sustainability" in group_l): matched = True
                    elif sl == "gsb" and "gsb" in group_l: matched = True
                    elif sl == "careered" and ("career" in group_l or "careered" in url_l): matched = True
                    elif sl == "cardinalatwork" and ("cardinal at work" in group_l or "worklife" in url_l): matched = True
                    elif sl == "cardinalnights" and "cardinal nights" in group_l: matched = True
                    elif sl in group_l: matched = True
                if not matched: continue

            # Topic interests: boost matching events (not a hard filter)
            topic_boost = 0.0
            if prefs.get("topics"):
                kws = [w.lower() for w in re.findall(r'\b[a-z]{3,}\b', prefs["topics"]) if w.lower() not in ["events", "stanford", "interested"]]
                if kws:
                    matches = sum(1 for kw in kws if kw in title_l or kw in desc_l or kw in topic_str)
                    topic_boost = matches * 5.0  # +5 per matching keyword

            # Filter: Perks
            pref_perks = prefs.get("perks", ["All"])
            if "All" not in pref_perks:
                if "Free Food" in pref_perks and not _detect_free_food(title_l + desc_l): continue
                if "Swag" in pref_perks and not _detect_merch(title_l + desc_l): continue

            # Filter: Formats
            pref_formats = prefs.get("formats", ["All"])
            if "All" not in pref_formats:
                is_reg = _requires_registration(event)
                if "Registration" in pref_formats and not is_reg: continue
                if "Drop-in" in pref_formats and is_reg: continue

            # Ranking
            score = 1.0
            etype = event.get("type", "")
            is_conference_or_talk = etype in ["Lecture/Presentation/Talk", "Conference/Symposium"]
            # Doerr School includes: Woods Institute, Precourt Institute, Earth & Planetary Sciences,
            # Earth Systems, Center for Ocean Solutions, Hopkins Marine Station, Energy, Environment, etc.
            doerr_keywords = [
                "doerr", "sustainability", "woods institute", "precourt",
                "earth", "ocean", "marine", "energy", "environment",
                "climate", "geophysics", "water in the west",
                "center for ocean solutions", "hopkins marine",
                "earth system", "storagex"
            ]
            is_doerr = any(kw in group_l or kw in topic_str for kw in doerr_keywords)
            is_gsb = "gsb" in group_l
            is_priority_sponsor = is_doerr or is_gsb

            # Doerr/GSB conferences/talks are unmissable — always on top
            if is_conference_or_talk and is_priority_sponsor:
                score += 100.0
            elif is_priority_sponsor:
                score += 15.0
            elif is_conference_or_talk:
                score += 4.0

            # Demote low-priority event types (exhibitions, tours, performances)
            low_priority_types = ["Exhibition", "Tour", "Performance", "Social Event/Reception", "Meeting"]
            if etype in low_priority_types:
                score -= 10.0

            ai_boost = 0.0
            for t in event.get("topics", []):
                tl = t.lower()
                ai_boost += interest_weights["topics"].get(tl, 0) * 0.5
            ai_boost += interest_weights["sponsors"].get(group_l, 0) * 2.0
            
            penalty = 0.0
            for t in event.get("topics", []):
                tl_match = t.lower()
                penalty -= interest_weights["hidden_topics"].get(tl_match, 0) * 5.0
                if tl_match in interest_weights["disliked_topics"]:
                    penalty -= 50.0 # Heavy explicit dislike penalty

            penalty -= interest_weights["hidden_sponsors"].get(group_l, 0) * 5.0
            if group_l in interest_weights["disliked_sponsors"]:
                penalty -= 50.0 # Heavy explicit dislike penalty
            
            if _is_recurring(event): 
                penalty -= 30.0 # Standard penalty
                # Extra penalty if it's not a talk/conference
                if etype not in ["Lecture/Presentation/Talk", "Conference/Symposium"]:
                    penalty -= 20.0

            final_score = score + ai_boost + topic_boost + penalty
            event_copy = dict(event)
            event_copy["match_score"] = round(float(final_score), 1)
            event_copy["is_registration"] = _requires_registration(event)
            event_copy["is_recurring"] = _is_recurring(event) or _normalize_title(event.get("title", "")) in duplicate_titles
            event_copy["is_doerr"] = is_doerr
            event_copy["is_gsb"] = is_gsb
            combined_text = f"{title_l} {desc_l}"
            event_copy["has_free_food"] = _detect_free_food(combined_text)
            event_copy["has_merch"] = _detect_merch(combined_text)
            personalized.append(event_copy)

        personalized.sort(key=lambda x: (-x["match_score"], x.get("time") or ""))
        return personalized
    except Exception as e:
        print(f"Error personalizing: {e}")
        return all_events

# ---------- Routes ----------

@app.get("/api/events")
def get_events(request: Request):
    user_id = _get_user_id(request)
    prefs = get_preferences(user_id)
    return get_personalized_events(fetch_and_cache_events(), prefs)

@app.get("/api/events/public")
def get_events_public():
    """Public endpoint — no personalization, just ranked events."""
    return get_personalized_events(fetch_and_cache_events())

@app.get("/api/preferences")
def get_prefs(request: Request):
    user_id = _get_user_id(request)
    return get_preferences(user_id)

@app.get("/api/user")
def get_user(request: Request):
    """Return current user info (for showing profile in UI)."""
    user_id = _get_user_id(request)
    from database import get_db
    conn = get_db()
    user = conn.execute("SELECT id, email, name, picture FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user:
        return dict(user)
    return {"id": user_id, "email": None, "name": None, "picture": None}

@app.post("/api/preferences")
def update_prefs_route(update: PreferencesUpdate, request: Request):
    user_id = _get_user_id(request)
    return update_preferences(user_id, update.dict(exclude_unset=True))

@app.post("/api/hide")
def hide_event(req: HideRequest, request: Request):
    user_id = _get_user_id(request)
    if req.is_hidden:
        target = next((e for e in events_cache["events"] if e.get("id") == req.event_id), None)
        add_action(user_id, req.event_id, "hidden",
                   title=target.get("title", "") if target else "",
                   group_name=target.get("group_name", "") if target else "")
    else:
        remove_action(user_id, req.event_id, "hidden")
    return {"status": "ok"}

@app.post("/api/interested")
def mark_interested(req: InterestedRequest, request: Request):
    user_id = _get_user_id(request)
    if req.is_interested:
        add_action(user_id, req.event_id, "interested")
    else:
        remove_action(user_id, req.event_id, "interested")
    return {"status": "ok"}

@app.post("/api/calendar_added")
def add_calendar(req: CalendarAddedRequest, request: Request):
    user_id = _get_user_id(request)
    add_action(user_id, req.event_id, "calendar_added")
    add_action(user_id, req.event_id, "interested")
    return {"status": "ok"}

@app.post("/api/dislike")
def dislike_event(req: DislikeRequest, request: Request):
    user_id = _get_user_id(request)
    target = next((e for e in events_cache["events"] if e.get("id") == req.event_id), None)
    if target:
        add_action(user_id, req.event_id, "disliked",
                   title=target.get("title", ""),
                   group_name=str(target.get("group_name", "")).lower(),
                   topics=[t.lower() for t in target.get("topics", [])])
    return {"status": "ok"}

@app.post("/api/not-interested")
def not_interested(req: NotInterestedRequest, request: Request):
    user_id = _get_user_id(request)
    target = next((e for e in events_cache["events"] if e.get("id") == req.event_id), None)
    if target:
        add_action(user_id, req.event_id, "hidden",
                   title=target.get("title", ""),
                   group_name=target.get("group_name", ""))
        expires = (datetime.now(timezone.utc) + timedelta(days=req.months * 30)).isoformat()
        add_action(user_id, req.event_id, "not_interested",
                   title=target.get("title", ""),
                   group_name=target.get("group_name", ""),
                   expires_at=expires)
    return {"status": "ok"}

def _scheduled_refresh():
    """Force-refresh events from Stanford API."""
    events_cache["last_fetched"] = 0  # Reset cache to force fresh fetch
    fetch_and_cache_events()
    print(f"[scheduler] Refreshed events at {datetime.now()}: {len(events_cache['events'])} events")

@app.on_event("startup")
def startup():
    # Auto-refresh events every 30 minutes
    scheduler.add_job(_scheduled_refresh, 'interval', minutes=30, id='refresh_events')
    scheduler.start()
    threading.Thread(target=fetch_and_cache_events, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
