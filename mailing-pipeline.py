DRY_RUN = True

import json
import os
import xml.etree.ElementTree as ET
import requests
from premailer import transform
import tomllib
from pathlib import Path

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT
# ==========================================
ALLOWED_CATEGORIES = {"comics", "events", "newsletters"}
MAILERLITE_API_KEY = os.getenv("MAILERLITE_API_KEY", "your_mailerlite_api_key")



# fetch information from hugo.toml
HUGO = tomllib.load(open("hugo.toml", "rb"))
SENDER_NAME = HUGO["title"]
SITE_URL = HUGO["baseURL"]
SENDER_EMAIL = HUGO["email"]

# Relative project paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH   = BASE_DIR / "email-template.html"
SENT_POSTS_PATH = BASE_DIR / "sent_posts.json"
#HARDCODED RSS FEEDS: one english, one maltese.
RSS_LANG_PATHS = [
    BASE_DIR / "public" / "en" / "index.xml",
    BASE_DIR / "public" / "mt" / "index.xml",
]


# MailerLite API Endpoint (v3)
MAILERLITE_API_URL = "https://connect.mailerlite.com/api/campaigns"

# Map (Language, Category) to MailerLite Group IDs
SEGMENT_MAP = {
    "comics": {
        "en": "200021722566493719",
        "mt": "200021561893193536",
    },
    "events": {
        "en": "200420005459789243",
        "mt": "200420047752005247",
    },
    "newsletters": {
        "en": "200419938428520315",
        "mt": "200419980685084578",
    },
}

# XML Namespaces inside Hugo's RSS
NAMESPACES = {'content': 'http://purl.org/rss/1.0/modules/content/',}

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def load_sent_posts() -> set:
    """Loads recorded GUIDs from sent_posts.json."""
    if os.path.exists(SENT_POSTS_PATH):
        with open(SENT_POSTS_PATH, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

def save_sent_posts(sent_guids: set):
    """Persists sent GUIDs back to sent_posts.json."""
    with open(SENT_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(sent_guids)), f, indent=2)

def build_email_html(template_raw: str, title: str, content: str, permalink: str, lang: str, linkText:str, copyrightText:str, unsubscribeText:str) -> str:
    """Injects data into template placeholders and inlines CSS via premailer.
    Args: all the variables that must be injected into email-template.html.
        >template_raw (str): Raw HTML template with placeholders.
        >title (str): Post title.
        >content (str): Post content (HTML).
        >permalink (str): URL to the post.
        >lang (str): Language code (e.g., 'en', 'mt').
        >linkText (str): Localized text for the "View on Website" link.
        >copyrightText (str): Localized copyright text.
        >unsubscribeText (str): Localized text for unsubscribe link.
        
        returns >inlined_html (str): Final HTML with placeholders replaced and CSS inlined."""
    
    # 1. Standard Placeholder String Replacements
    html_filled = template_raw
    html_filled = html_filled.replace("{{ LANG }}", lang)
    html_filled = html_filled.replace("{{ TITLE }}", title)
    html_filled = html_filled.replace("{{ CONTENT }}", content)
    html_filled = html_filled.replace("{{ PERMALINK }}", permalink)
    html_filled = html_filled.replace("{{ LINK_TEXT }}", linkText)
    html_filled = html_filled.replace("{{ UNSUBSCRIBE_TEXT }}", unsubscribeText)
    html_filled = html_filled.replace("{{ COPYRIGHT_TEXT }}", copyrightText)
    html_filled = html_filled.replace("{{ SITE_URL }}", SITE_URL)

    # 2. Convert CSS stylesheet into inline style="" attributes
    inlined_html = transform(html_filled)
    return inlined_html

def send_to_mailerlite(title: str, inlined_html: str, target_group_id: str) -> bool:
    """Creates and dispatches a campaign in MailerLite via API v3."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MAILERLITE_API_KEY}"
    }

    payload = {
        "name": f"Auto-Dispatch: {title}",
        "type": "regular",
        "emails": [
            {
                "subject": title,
                "from_name": SENDER_NAME,
                "from": SENDER_EMAIL,
                "content": inlined_html
            }
        ],
        "groups": [target_group_id]
    }

    response = requests.post(MAILERLITE_API_URL, headers=headers, json=payload)

    if response.status_code in (200, 201):
        print(f"Successfully created campaign for: '{title}' (Group: {target_group_id})")
        return True
    else:
        print(f"MailerLite API Error [{response.status_code}]: {response.text}")
        return False

# ==========================================
# 3. MAIN EXECUTION PIPELINE
# ==========================================
def main():
    sent_posts = load_sent_posts()#Load previously sent post GUIDs from sent_posts.json using helper function

    #GEt the html file sorted
    if not os.path.exists(TEMPLATE_PATH):     #verify the .html file exists
        print(f"❌ Error: Email template not found at {TEMPLATE_PATH}")
        return
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:     #read the .html file
        template_raw = f.read() #load what we read into memort    
     
     
    for rssLangPath in RSS_LANG_PATHS:
        
        #get our oublic/mt/index.cml sorted and public/en/index.xml sorted
        if not rssLangPath.exists():
            print(f"⚠️ RSS feed not found at {rssLangPath}. Did you run 'hugo'?")
            continue
        
        lang = rssLangPath.parent.name.lower()
        print(f"\n📄 Reading RSS feed: {rssLangPath.relative_to(BASE_DIR)} [Lang: '{lang}']")

        #for the ET.parse() to work, the .xml file must start with <?xml version="1.0" encoding="utf-8"?>
        with open(rssLangPath, "r", encoding="utf-8") as f:
            if not f.readline().startswith("<?xml"):
                print(f"❌ Error: {rssLangPath.name} has junk or whitespace on line 1. Run Hugo rebuild!")
                continue

        tree = ET.parse(rssLangPath) #an imported function that convert xml into a searchable python tree
        root = tree.getroot() #we get the root of this tree ;)

        # 1. Extract feed-level settings ONCE off <channel>
        linkText = (root.findtext("./channel/website_link_text")).strip()
        unsubscribeText = (root.findtext("./channel/unsubscribe_text")).strip()
        copyrightText = (root.findtext("./channel/copyright")).strip()
        
        items = root.findall("./channel/item") #items list extracts all the instances (like <<content:encoded> in email-template.html <channel> section
        print(f"Found {len(items)} items in feed.")

        for item in items: #loop through every item (which is every post) in the RSS feed
            guid = item.findtext("guid") #Globally Unique ID
            title = item.findtext("title")
            permalink = item.findtext("link")
            
            content_elem = item.find("content:encoded", NAMESPACES) # Extract <content:encoded>
            content = content_elem.text if content_elem is not None else item.findtext("description", "")
            
            category     = (item.findtext("category") or "").strip().lower()
            if category not in ALLOWED_CATEGORIES: #ignore the About Page, Member Page, etc.
                continue

            #validate data:
            fields = {
            "guid": guid, 
            "title": title,
            "permalink": permalink,
            "content": content,
            "language":lang,
            "category": category,
            "website_link_text": linkText,
            "unsubscribe_text": unsubscribeText,
            "copyright": copyrightText
            }
            missing = [name for name, value in fields.items() if not value]

            if missing: 
                print(f" ;) BLOCKED: '{title or 'UNTITLED'}' missing fields: {', '.join(missing)}")
                continue

            # 1. Skip if post is not new
            if guid in sent_posts: #sendt post is the json history looaded
                print(f":3 Skipping already sent post: {title} ({guid})")
                continue

            # 2. Determine target MailerLite group
            target_group = SEGMENT_MAP.get(category.lower(), {}).get(lang.lower())
            if not target_group:
                print(f"❌AAAA!!!❌❌❌❌>:((❌❌ BLOCKED No group mapping found for lang='{lang}' and category='{category}'. Skipping '{title}'.")
                continue

            print(f"Processing new post: '{title}' [{lang}/{category}]")

            # 3. Build inlined HTML
            email_html = build_email_html(template_raw, title, content, permalink, lang, linkText, copyrightText, unsubscribeText)

            # 4. Dispatch via MailerLite API OR the dry run kicks in
            # 4. DRY RUN vs LIVE DISPATCH
            if DRY_RUN:
                # Create a safe filename from the post title
                safe_filename = "".join(c if c.isalnum() else "_" for c in title).lower()
                preview_filename = f"preview_{lang}_{safe_filename}.html"
                
                with open(preview_filename, "w", encoding="utf-8") as f:
                    f.write(email_html)
                    
                print(f" [DRY RUN SUCCESS] Validated '{title}' [{lang}/{category}]")
                print(f"   ↳ Would dispatch to MailerLite Group ID: {target_group}")
                print(f"   ↳ Saved email preview to: {preview_filename}\n")
                continue  # Do NOT call MailerLite or write to sent_posts.json

            success = send_to_mailerlite(title, email_html, target_group)

            # 5. Update tracking store upon successful API response
            if success:
                sent_posts.add(guid) #the sendt post is now old
                save_sent_posts(sent_posts) 

if __name__ == "__main__":
    main()