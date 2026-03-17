# Stanford Events Calendar

**[Live Demo](https://stanford-events.fly.dev)**

A personalized events dashboard for the Stanford community. It fetches events daily, filters them by user preference, and presents them in an interactive calendar and smart-sorted feed.

Live events are fetched from [events.stanford.edu](https://events.stanford.edu) and ranked by relevance.

## Features

- **Smart ranking** — Conferences and seminars from the Doerr School and GSB are prioritized. Recurring events (exhibitions, weekly meetings) are detected and moved to the bottom.
- **Personalization** — Sign in with Google to save events, set topic preferences, filter by type/location/sponsor, and train the algorithm with hide/dislike/not-interested actions.
- **Calendar integration** — Add events to Google Calendar, Outlook, or Apple Calendar with one click.
- **Perks detection** — Events offering free food or swag are automatically flagged (visible to signed-in users).
- **Auto-updating** — Events refresh every 30 minutes from Stanford's API.

## How It Works

**Public view (not signed in):**
- Browse curated events from the Doerr School, other schools or all of Stanford
- View details and add events to your calendar

**Personal view (signed in with Google):**
- Full sidebar with filters (event type, location, sponsor, perks, format)
- Save events, hide events, mark "not interested" (suppresses similar events for 3 months)
- Algorithm learns from your actions to improve recommendations over time

## Recommendation Algorithm

Events are ranked using a combination of editorial curation and personal learning:

**Editorial ranking (applies to everyone):**
- Conferences and talks from the Doerr School of Sustainability and GSB are always prioritized
- Academic events (seminars, lectures, workshops) rank higher than passive events (exhibitions, tours, performances)
- Recurring events (weekly meetings, standing exhibitions) are detected automatically and deprioritized

**Personal learning (builds over time per user):**
- Saving an event boosts similar events (by topic and sponsor) in future rankings
- Hiding an event slightly lowers similar events
- Disliking multiple events from the same topic or sponsor progressively demotes all events from that source
- Marking "Not Interested" suppresses events with similar titles for 3 months
- Topic keywords you set in preferences boost matching events

## Setup

### Prerequisites
- Python 3.9+

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
cd backend
python main.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.