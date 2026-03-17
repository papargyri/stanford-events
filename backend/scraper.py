import requests
import json
import logging
import os
import re
import concurrent.futures
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class StanfordEventsScraper:
    def __init__(self):
        # We observed the API endpoint used in the Stanford events page
        self.api_url = "https://events.stanford.edu/api/2/events"
        # Basic cache for scraped time strings to avoid re-fetching the same URL
        self._time_string_cache = {}
    
    def fetch_events(self, days=30):
        all_raw_events = []
        page = 1
        max_pages = 10 # ~1000 raw events for 60-day window
        
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        
        try:
            while page <= max_pages:
                params = {
                    "pp": 100,  # items per page
                    "days": days,
                    "page": page
                }
                response = requests.get(self.api_url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                events = data.get("events", [])
                if not events:
                    break
                    
                all_raw_events.extend(events)
                
                total_pages = data.get("page", {}).get("total", 1)
                if page >= total_pages:
                    break
                    
                page += 1
                
            return self._parse_events(all_raw_events)
        except Exception as e:
            print(f"Error fetching events: {e}")
            return []
            
    def _scrape_time_string_from_html(self, url: str) -> str:
        """Fallback to scrape the exact '4:30pm to 5:20pm' string from the event page HTML since Localist API drops end times."""
        if not url: return ""
        
        if url in self._time_string_cache:
            return self._time_string_cache[url]
            
        try:
            res = requests.get(url, timeout=2)
            if res.status_code == 200:
                # Look for patterns like "4:30pm to 5:20pm PT"
                match = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?\s*to\s*\d{1,2}:\d{2}\s*(?:am|pm)?\s*(?:PT)?)', res.text, re.IGNORECASE)
                if match:
                    time_str = match.group(1).strip()
                    self._time_string_cache[url] = time_str
                    return time_str
        except:
            pass
            
        self._time_string_cache[url] = ""
        return ""

    def _parse_events(self, raw_events):
        parsed_events = []
        
        # Broadened keywords so we grab results for all our target schools and interests
        inclusion_keywords = [
            # Sustainability
            "sustainability", "climate", "energy", "earth", "environment", "ocean", "geophysics", "biology", "nature", "conservation", "policy", "technology", "innovation", "future",
            # GSB
            "gsb", "business", 
            # TAPS / Arts
            "taps", "theater", "theatre", "arts", "dance", "performance", "drama", "music",
            # GSE / Education
            "gse", "education",
            # Engineering
            "engineering", "soe",
            # Sports
            "sport", "athletics", "football", "basketball", "soccer", "tennis", "volleyball", "baseball",
            # Perks
            "swag", "t-shirt", "giveaway", "merch", "free food", "pizza", "lunch", "refreshments",
            # Postdoc Office
            "postdoc", "postdoctoral",
            # Continuing Studies
            "continuing studies",
            # Cardinal Nights
            "cardinal nights",
            # Cardinal at Work & Career Ed (Broader categories)
            "human resources", "uhr", "worklife", "bewell", "career education", "vpge", "professional development", "career fair"
        ]
        
        for item in raw_events:
            event = item.get("event", {})
            title = event.get("title", "")
            description = event.get("description_text", "")
            departments = [d.get("name", "") for d in event.get("departments", [])]
            tags = event.get("tags", [])
            types = [t.get("name", "") for t in event.get("filters", {}).get("event_types", [])]
            
            # Combine all text for filtering
            all_text = f"{title} {description} {' '.join(departments)} {' '.join(tags)}".lower()
            
            # Filter for relevant events 
            is_relevant = any(kw in all_text for kw in inclusion_keywords)
            
            # Also include if Doerr School is in departments
            is_doerr = any("doerr" in d.lower() for d in departments)
            
            if is_relevant or is_doerr:
                # Extract event types (Lecture, Seminar, etc.)
                event_type = types[0] if types else "Event"
                
                # Check if it's a talk/lecture/presentation type based on title/type
                type_keywords = ["lecture", "presentation", "talk", "seminar", "symposium", "colloquium"]
                if any(kw in all_text for kw in type_keywords) and event_type == "Event":
                    event_type = "Lecture/Presentation/Talk"
                
                # Add temporary placeholder
                parsed_events.append({
                    "id": event.get("id"),
                    "title": title,
                    "description": description[:200] + "..." if len(description) > 200 else description,
                    "date": event.get("first_date"),
                    "time": event.get("event_instances", [{}])[0].get("event_instance", {}).get("start"),
                    "end_time": event.get("event_instances", [{}])[0].get("event_instance", {}).get("end"),
                    "status": event.get("status", "live"),
                    "display_time": "", # Will fill concurrently
                    "location_name": event.get("location_name") or event.get("location") or "Stanford Campus",
                    "address": event.get("address") or event.get("location_name") or "Stanford, CA",
                    "url": event.get("localist_url"),
                    "group_name": departments[0] if departments else "",
                    "type": event_type,
                    "topics": tags + departments,
                    "image_url": event.get("photo_url")
                })
                
        # Fill display times concurrently
        def fetch_time(event_dict):
            event_dict["display_time"] = self._scrape_time_string_from_html(event_dict["url"])
            return event_dict
            
        if parsed_events:
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                parsed_events = list(executor.map(fetch_time, parsed_events))
                
        # Sort by date
        parsed_events.sort(key=lambda x: x.get("time") or "9999")
        return parsed_events

# Test the scraper
if __name__ == "__main__":
    scraper = StanfordEventsScraper()
    events = scraper.fetch_events(days=14)
    print(f"Found {len(events)} relevant events.")
    if events:
        print(json.dumps(events[0], indent=2))
