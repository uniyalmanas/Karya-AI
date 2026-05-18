import os
import sys
import asyncio
import json
import re
import base64
import traceback
import httpx
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from dotenv import load_dotenv
from google.api_core.exceptions import ResourceExhausted
from playwright.async_api import async_playwright

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(AGENT_DIR, ".env"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

try:
    from google import genai as google_genai
    from google.genai import types as genai_types
    HAS_GOOGLE_GENAI = True
except ImportError:
    google_genai = None
    genai_types = None
    HAS_GOOGLE_GENAI = False

try:
    import google.generativeai as old_genai
    HAS_OLD_GENERATIVEAI = True
except ImportError:
    old_genai = None
    HAS_OLD_GENERATIVEAI = False

try:
    from groq import AsyncGroq
    HAS_GROQ = True
except ImportError:
    AsyncGroq = None
    HAS_GROQ = False

if HAS_OLD_GENERATIVEAI and GEMINI_API_KEY:
    old_genai.configure(api_key=GEMINI_API_KEY)

if HAS_GROQ and GROQ_API_KEY:
    groq_client = AsyncGroq(api_key=GROQ_API_KEY)
else:
    groq_client = None

def clean_json_response(text):
    return re.sub(r'```json|```', '', text).strip()

async def fetch_weather_via_wttr(location: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url = f"https://wttr.in/{location}?format=%l:+%c+%t"
            response = await client.get(url, headers={"User-Agent": "KaryaAI-Agent/1.0"})
            if response.status_code == 200:
                return response.text.strip()
            print(f"⚠️ wttr.in responded with status {response.status_code}")
    except Exception as e:
        print(f"⚠️ Weather fallback failed: {e}")
    return None


async def fetch_ipl_score_via_search(goal: str):
    try:
        query = goal.strip().replace(' ', '+')
        url = f"https://www.bing.com/search?q={query}"
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
            })
            if response.status_code != 200:
                print(f"⚠️ Search fallback failed with status {response.status_code}")
                return None
            text = response.text
            # Try to extract the scorecard or summary from the search page text
            score_match = re.search(r'([0-9]+\/[0-9]+\s*\([0-9]+\s*overs\)?\s*-\s*[0-9]+\/[0-9]+\s*\([0-9]+\s*overs\)?)', text)
            if score_match:
                return f"IPL scorecard summary: {score_match.group(1)}"
            summary_match = re.search(r'IPL.*?(?:score|scorecard|result)[^<]{20,120}', text, flags=re.IGNORECASE)
            if summary_match:
                return summary_match.group(0).strip()
            # Fallback to a shorter plain-text guess
            return "Unable to extract the IPL scorecard directly from search results."
    except Exception as e:
        print(f"⚠️ IPL search fallback failed: {e}")
    return None


def parse_weather_location(goal: str):
    goal = goal.strip()
    search = re.search(r'weather(?: of| in)?\s+([A-Za-z \-]+)', goal, flags=re.IGNORECASE)
    if search:
        return search.group(1).strip()

    search = re.search(r'temperature(?: of| in)?\s+([A-Za-z \-]+)', goal, flags=re.IGNORECASE)
    if search:
        return search.group(1).strip()

    tokens = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', goal)
    return tokens[-1] if tokens else None


INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    "Chandigarh", "Andaman and Nicobar", "Dadra and Nagar Haveli", "Daman and Diu",
    "Lakshadweep"
]


def write_mission_result(mission_id: str, data: dict):
    result_path = os.path.join(os.path.dirname(__file__), f"mission_{mission_id}.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"[Result] Saved mission output to {result_path}")


def classify_india_workflow(goal: str) -> str | None:
    normalized_goal = goal.lower()

    if any(term in normalized_goal for term in ["gem", "tender", "bid", "procurement", "eprocure"]):
        return "gem_tender_discovery"

    if any(term in normalized_goal for term in ["gst", "gstr", "eway", "e-way", "invoice mismatch"]):
        return "gst_assistant"

    if any(term in normalized_goal for term in ["udyam", "msme certificate", "msme registration"]):
        return "udyam_assistant"

    return None


def parse_budget_limit(goal: str) -> int | None:
    normalized = goal.lower().replace(",", "")
    match = re.search(r'(?:under|below|less than|upto|up to|max(?:imum)?)\s*(?:inr|rs\.?|rupees)?\s*([0-9]+(?:\.[0-9]+)?)\s*(lakh|lakhs|lac|lacs|crore|cr|k)?', normalized)
    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2) or ""

    if unit in ["lakh", "lakhs", "lac", "lacs"]:
        amount *= 100000
    elif unit in ["crore", "cr"]:
        amount *= 10000000
    elif unit == "k":
        amount *= 1000

    return int(amount)


def parse_tender_filters(goal: str) -> dict:
    state = None
    for candidate in INDIAN_STATES:
        if re.search(rf'\b{re.escape(candidate)}\b', goal, flags=re.IGNORECASE):
            state = candidate
            break

    category = goal
    cleanup_patterns = [
        r'\b(find|search|show|track|monitor|get|daily)\b',
        r'\b(gem|government|govt|tender|tenders|bid|bids|procurement|opportunities)\b',
        r'\b(in|for|under|below|less than|upto|up to|max|maximum)\b',
        r'\b(INR|rs\.?|rupees)\b',
        r'[0-9,.]+\s*(lakh|lakhs|lac|lacs|crore|cr|k)?',
    ]

    for pattern in cleanup_patterns:
        category = re.sub(pattern, " ", category, flags=re.IGNORECASE)

    if state:
        category = re.sub(re.escape(state), " ", category, flags=re.IGNORECASE)

    category = " ".join(category.split()).strip(" -,:")
    if not category:
        category = "relevant business supplies"

    return {
        "category": category,
        "state": state,
        "max_value_inr": parse_budget_limit(goal),
    }


def strip_html(value: str) -> str:
    return " ".join(unescape(re.sub(r'<[^>]+>', ' ', value)).split())


def normalize_search_link(link: str) -> str:
    link = unescape(link)
    if link.startswith("/url?"):
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        if query.get("q"):
            return query["q"][0]
    if "bing.com/ck/a" in link and "u=" in link:
        query = parse_qs(urlparse(link).query)
        encoded = query.get("u", [""])[0]
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        try:
            return unquote(encoded)
        except Exception:
            return link
    return link


def add_unique_opportunity(opportunities: list[dict], candidate: dict):
    link = candidate.get("link", "")
    title = candidate.get("title", "")
    if not title or not link:
        return

    existing_links = {item.get("link") for item in opportunities}
    if link in existing_links:
        return

    opportunities.append(candidate)


def parse_bing_results(html_text: str) -> list[dict]:
    opportunities = []
    blocks = re.findall(r'<li class="b_algo".*?</li>', html_text, flags=re.IGNORECASE | re.DOTALL)

    for block in blocks[:10]:
        title_match = re.search(r'<h2.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.IGNORECASE | re.DOTALL)
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.IGNORECASE | re.DOTALL)
        if not title_match:
            continue

        add_unique_opportunity(opportunities, {
            "title": strip_html(title_match.group(2)),
            "link": normalize_search_link(title_match.group(1)),
            "snippet": strip_html(snippet_match.group(1)) if snippet_match else "",
            "source": "bing_public_search"
        })

    if opportunities:
        return opportunities

    for link, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, flags=re.IGNORECASE | re.DOTALL):
        clean_title = strip_html(title)
        clean_link = normalize_search_link(link)
        if "gem.gov.in" not in clean_link and "bidplus.gem.gov.in" not in clean_link:
            continue
        add_unique_opportunity(opportunities, {
            "title": clean_title,
            "link": clean_link,
            "snippet": "",
            "source": "bing_public_search"
        })
        if len(opportunities) >= 8:
            break

    return opportunities


def parse_duckduckgo_results(html_text: str) -> list[dict]:
    opportunities = []
    result_blocks = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', html_text, flags=re.IGNORECASE | re.DOTALL)

    for link, title in result_blocks[:10]:
        clean_link = normalize_search_link(link)
        if clean_link.startswith("//"):
            clean_link = f"https:{clean_link}"

        add_unique_opportunity(opportunities, {
            "title": strip_html(title),
            "link": clean_link,
            "snippet": "",
            "source": "duckduckgo_public_search"
        })

    return opportunities


async def fetch_public_tender_opportunities(search_query: str) -> tuple[list[dict], list[dict]]:
    search_sources = [
        {
            "name": "bing",
            "url": f"https://www.bing.com/search?q={quote_plus(search_query)}",
            "parser": parse_bing_results,
        },
        {
            "name": "duckduckgo",
            "url": f"https://duckduckgo.com/html/?q={quote_plus(search_query)}",
            "parser": parse_duckduckgo_results,
        },
    ]
    opportunities = []
    diagnostics = []

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for source in search_sources:
            try:
                response = await client.get(source["url"], headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                response.raise_for_status()
                parsed = source["parser"](response.text)
                for item in parsed:
                    add_unique_opportunity(opportunities, item)
                diagnostics.append({
                    "source": source["name"],
                    "status": response.status_code,
                    "results_extracted": len(parsed),
                })
            except Exception as exc:
                diagnostics.append({
                    "source": source["name"],
                    "status": "failed",
                    "error": str(exc),
                })

            if len(opportunities) >= 8:
                break

    return opportunities[:8], diagnostics


async def run_public_tender_search(goal: str, mission_id: str):
    filters = parse_tender_filters(goal)
    query_parts = ["GeM tender", filters["category"]]

    if filters["state"]:
        query_parts.append(filters["state"])
    if filters["max_value_inr"]:
        query_parts.append(f"under INR {filters['max_value_inr']}")

    query_parts.append("site:gem.gov.in OR site:bidplus.gem.gov.in")
    search_query = " ".join(query_parts)
    search_url = f"https://www.bing.com/search?q={quote_plus(search_query)}"
    official_gem_url = "https://bidplus.gem.gov.in/all-bids"

    print("[Planner] Selected workflow: gem_tender_discovery")
    print(f"[Tender] Category: {filters['category']}")
    print(f"[Tender] State: {filters['state'] or 'All India'}")
    if filters["max_value_inr"]:
        print(f"[Tender] Budget ceiling: INR {filters['max_value_inr']}")
    print("[Tender] Searching public tender indexes.")

    opportunities, diagnostics = await fetch_public_tender_opportunities(search_query)

    result = {
        "workflow": "gem_tender_discovery",
        "status": "completed",
        "filters": filters,
        "search_query": search_query,
        "search_url": search_url,
        "official_gem_bids_url": official_gem_url,
        "opportunities": opportunities,
        "search_diagnostics": diagnostics,
        "next_actions": [
            "Verify each opportunity on the official GeM portal before bidding.",
            "Open the official GeM bids page and apply the parsed category, state, and budget filters.",
            "Shortlist tenders by eligibility, EMD, delivery location, and closing date.",
            "Prepare documents: GST certificate, PAN, Udyam/MSME certificate if available, product catalogue, authorization letter, financial statements, and past performance documents.",
            "Ask for human approval before bid submission, pricing, payment, or DSC signing."
        ],
        "human_approval_required_for": [
            "Portal login",
            "OTP or CAPTCHA",
            "Final bid submission",
            "Price quote confirmation",
            "Digital signature or payment"
        ]
    }

    if not opportunities:
        result["status"] = "needs_operator_review"
        result["confidence"] = "low"
        result["note"] = "No public search results were extracted. The workflow still produced filters, search URL, and bidding checklist so an operator can continue from the official portal."
    else:
        result["confidence"] = "medium"

    write_mission_result(mission_id, result)


async def run_gst_assistant(goal: str, mission_id: str):
    print("[Planner] Selected workflow: gst_assistant")
    result = {
        "workflow": "gst_assistant",
        "status": "needs_human_login",
        "summary": "Karya can prepare GST portal work, but login, OTP, CAPTCHA, and final filing need human approval.",
        "supported_next_steps": [
            "Check GST filing status",
            "Download GSTR-1, GSTR-3B, or GSTR-2B",
            "Create due-date reminders",
            "Prepare an invoice mismatch checklist"
        ],
        "required_from_user": [
            "GSTIN",
            "GST portal username",
            "Human-provided OTP/CAPTCHA during login",
            "Return period or financial year"
        ],
        "human_approval_required_for": [
            "Login OTP/CAPTCHA",
            "Any filing submission",
            "Any payment or ledger offset"
        ],
        "original_goal": goal
    }
    write_mission_result(mission_id, result)


async def run_udyam_assistant(goal: str, mission_id: str):
    print("[Planner] Selected workflow: udyam_assistant")
    result = {
        "workflow": "udyam_assistant",
        "status": "needs_human_details",
        "summary": "Karya can organize MSME/Udyam certificate retrieval or update workflows after the user provides business identifiers.",
        "required_from_user": [
            "Udyam registration number if available",
            "Mobile/email access for OTP",
            "PAN/Aadhaar-linked owner approval where required"
        ],
        "safe_actions": [
            "Prepare document checklist",
            "Navigate to official Udyam portal",
            "Extract certificate status after human-approved login"
        ],
        "human_approval_required_for": [
            "OTP",
            "Aadhaar/PAN-linked verification",
            "Any final update or submission"
        ],
        "original_goal": goal
    }
    write_mission_result(mission_id, result)

# Interactive overlay markup injection logic
MARK_ELEMENTS_JS = """
() => {
    const oldMarkers = document.querySelectorAll('.karya-marker');
    oldMarkers.forEach(m => m.remove());

    const elements = document.querySelectorAll('input, button, a, select, textarea, [role="button"]');
    let index = 0;

    elements.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
            index++;
            el.setAttribute('data-karya-id', index);

            const marker = document.createElement('div');
            marker.className = 'karya-marker';
            marker.textContent = index;
            marker.style.position = 'absolute';
            marker.style.backgroundColor = 'red';
            marker.style.color = 'white';
            marker.style.fontSize = '12px';
            marker.style.fontWeight = 'bold';
            marker.style.padding = '2px 5px';
            marker.style.borderRadius = '3px';
            marker.style.zIndex = '1000000';
            marker.style.pointerEvents = 'none';

            const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            marker.style.left = `${rect.left + scrollLeft}px`;
            marker.style.top = `${rect.top + scrollTop}px`;

            document.body.appendChild(marker);
        }
    });
}
"""

async def get_brain_decision(img_path, goal):
    # Ensure file persistence pipeline is finished writing to disk before processing
    for _ in range(10):
        if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
            break
        await asyncio.sleep(0.2)

    try:
        with open(img_path, "rb") as f:
            img_data = f.read()
            base64_image = base64.b64encode(img_data).decode('utf-8')
    except Exception as file_err:
        print(f"❌ Storage Read Error: {file_err}")
        return None

    prompt = f"""
    Goal: {goal}
    Analyze the screenshot. Every interactive element on the page has a RED badge with a number on it.
    Decide the single best action to move toward the goal.

    Rules:
    1. If you need to click or type, specify the corresponding number from the red badge in "target_number".
    2. If the goal is met, set "action" to "FINISH" and provide data in "extracted_data".

    Return format MUST be raw valid JSON matching this schema exactly:
    {{
        "thought": "Your visual reasoning explaining why you selected that number",
        "action": "CLICK" | "TYPE" | "FINISH",
        "target_number": 5,
        "text": "text to type (leave empty if action is CLICK/FINISH)",
        "extracted_data": {{}}
    }}
    """

    async def run_groq_decision():
        if not HAS_GROQ or not groq_client:
            return None

        try:
            completion = await groq_client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }],
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as groq_err:
            print(f"⚠️ Groq engine error: {groq_err}")
            return {
                "engine_error": "groq_failed",
                "message": str(groq_err)
            }

    def parse_gemini_json(raw_text):
        try:
            return json.loads(clean_json_response(raw_text))
        except Exception as parse_err:
            print(f"⚠️ Gemini JSON parse failed: {parse_err}")
            return {
                "engine_error": "parse_failure",
                "message": str(parse_err)
            }

    async def run_gemini_decision():
        if not GEMINI_API_KEY:
            return {
                "engine_error": "no_gemini_key",
                "message": "GEMINI_API_KEY is not configured."
            }

        if HAS_GOOGLE_GENAI:
            try:
                client = google_genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[
                        prompt,
                        genai_types.Part.from_bytes(data=img_data, mime_type='image/png')
                    ],
                    config=genai_types.GenerateContentConfig(
                        response_mime_type='application/json'
                    )
                )
                return parse_gemini_json(response.text)
            except Exception as gemini_err:
                print(f"❌ Gemini (google.genai) engine error: {gemini_err}")
                print(traceback.format_exc())
                if isinstance(gemini_err, ResourceExhausted):
                    return {
                        "engine_error": "quota_exhausted",
                        "message": str(gemini_err)
                    }
                return {
                    "engine_error": "gemini_failed",
                    "message": str(gemini_err)
                }

        if HAS_OLD_GENERATIVEAI:
            try:
                model = old_genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content([
                    prompt,
                    {
                        "mime_type": "image/png",
                        "data": img_data
                    }
                ])
                return parse_gemini_json(response.text)
            except Exception as gemini_err:
                print(f"❌ Gemini (google.generativeai) engine error: {gemini_err}")
                print(traceback.format_exc())
                if isinstance(gemini_err, ResourceExhausted):
                    return {
                        "engine_error": "quota_exhausted",
                        "message": str(gemini_err)
                    }
                return {
                    "engine_error": "gemini_failed",
                    "message": str(gemini_err)
                }

        return {
            "engine_error": "no_gemini_package",
            "message": "No Gemini Python SDK is installed."
        }

    use_gemini = bool(GEMINI_API_KEY) and (HAS_GOOGLE_GENAI or HAS_OLD_GENERATIVEAI)
    use_groq = bool(GROQ_API_KEY) and HAS_GROQ and groq_client is not None

    if use_gemini:
        print("🔍 Primary strategy: Gemini")
        result = await run_gemini_decision()
        if result and not result.get("engine_error"):
            return result
        print("🔄 Gemini failed; falling back to Groq" if use_groq else "❌ Gemini failed and no Groq fallback available")
        if use_groq:
            groq_result = await run_groq_decision()
            return groq_result or result
        return result

    if use_groq:
        print("🔍 Primary strategy: Groq")
        return await run_groq_decision()

    print("❌ No Gemini or Groq API key configured.")
    return None

async def run_karya_agent(goal: str, mission_id: str = "fallback_id"):
    workflow = classify_india_workflow(goal)
    if workflow == "gem_tender_discovery":
        await run_public_tender_search(goal, mission_id)
        return

    if workflow == "gst_assistant":
        await run_gst_assistant(goal, mission_id)
        return

    if workflow == "udyam_assistant":
        await run_udyam_assistant(goal, mission_id)
        return

    weather_location = parse_weather_location(goal)
    if weather_location:
        print(f"🌤️ Detected weather request for '{weather_location}'. Using direct weather fallback.")
        weather_text = await fetch_weather_via_wttr(weather_location)
        if weather_text:
            extracted_result = {
                "weather": weather_text,
                "location": weather_location,
                "source": f"wttr.in/{weather_location}"
            }
            result_path = os.path.join(os.path.dirname(__file__), f"mission_{mission_id}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(extracted_result, f, ensure_ascii=False, indent=4)
            print(f"🏁 Weather fallback resolved directly and wrote {result_path}")
            return
        print("⚠️ Direct weather fallback failed; falling back to browser-driven execution.")

    if re.search(r'\bIPL\b|\bscorecard\b|\bscore card\b|\bcricket\b', goal, flags=re.IGNORECASE):
        print("🏏 Detected IPL/cricket query. Using direct search fallback.")
        ipl_text = await fetch_ipl_score_via_search(goal)
        if ipl_text:
            extracted_result = {
                "answer": ipl_text,
                "source": "bing.com search fallback"
            }
            result_path = os.path.join(os.path.dirname(__file__), f"mission_{mission_id}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(extracted_result, f, ensure_ascii=False, indent=4)
            print(f"🏁 IPL fallback resolved directly and wrote {result_path}")
            return
        print("⚠️ Direct IPL fallback failed; falling back to browser-driven execution.")

    async with async_playwright() as p:
        print(f"🎯 Mission: {goal}")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("🌐 Initializing Web Canvas...")
        
        # Check if the mission directive specifies a direct web URL footprint
        url_match = re.search(r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.(com|org|net|in|edu|co))', goal.lower())
        
        if url_match:
            target_url = url_match.group(1)
            target_url = target_url.rstrip(',')
            if not target_url.startswith('http'):
                target_url = 'https://' + target_url
            print(f"🚀 Direct domain pattern detected. Fast-routing browser directly to: {target_url}")
            await page.goto(target_url, wait_until="networkidle")
        else:
            print("🔍 General search pattern detected. Initializing via search engine index...")
            await page.goto("https://duckduckgo.com", wait_until="networkidle")
        
        extracted_result = None
        last_known_thought = "Agent initialized configuration environments."
        generated_screenshots = []
        engine_failures = 0

        for i in range(12):
            print(f"\n--- Step {i+1} ---")
            
            try:
                await page.wait_for_load_state("load", timeout=4000)
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass 

            try:
                await page.evaluate(MARK_ELEMENTS_JS)
            except Exception as eval_err:
                print("🔄 Layout refreshing mid-flight. Waiting for document context to re-stabilize...")
                try:
                    await page.wait_for_load_state("commit", timeout=3000)
                    await page.evaluate(MARK_ELEMENTS_JS)
                except Exception:
                    print("⚠️ Context mapping bypassed for this cycle.")
                    continue

            await asyncio.sleep(0.5) 
            
            screenshot_path = f"step_{i}_{mission_id}.png"
            generated_screenshots.append(screenshot_path)
            
            try:
                await page.screenshot(path=screenshot_path)
            except Exception as screenshot_err:
                print(f"⚠️ UI View refreshing, stalling frame synchronization...")
                await asyncio.sleep(1.5)
                try:
                    await page.screenshot(path=screenshot_path)
                except Exception:
                    continue
            
            res = await get_brain_decision(screenshot_path, goal)
            if not res:
                print("❌ Step aborted: Engines un-responsive.")
                engine_failures += 1
                if engine_failures >= 3:
                    raise RuntimeError("Agent engine failed repeatedly; aborting mission.")
                continue

            if isinstance(res, dict) and res.get("engine_error"):
                print(f"❌ Engine error: {res.get('message')}")
                if res.get("engine_error") == "quota_exhausted":
                    raise RuntimeError("Gemini quota exhausted; aborting mission.")
                engine_failures += 1
                if engine_failures >= 3:
                    raise RuntimeError("Agent engine failed repeatedly; aborting mission.")
                continue

            print(f"💭 AI Thought: {res.get('thought')}")
            if res.get('thought'):
                last_known_thought = res.get('thought')

            if res.get('action') == "FINISH":
                extracted_result = res.get('extracted_data') or {"summary": res.get('thought')}
                print("🏁 Mission Accomplished Explicitly!")
                break
            
            target_id = res.get("target_number")
            selector = f'[data-karya-id="{target_id}"]'
            
            try:
                if res['action'] == "TYPE":
                    await page.fill(selector, res['text'], timeout=3000)
                    await page.keyboard.press("Enter")
                    print(f"⌨️  Typed text into element [{target_id}]")
                    await page.wait_for_load_state("commit", timeout=2000)
                elif res['action'] == "CLICK":
                    await page.click(selector, timeout=3000)
                    print(f"鼠标 Clicked element [{target_id}]")
                    await page.wait_for_load_state("commit", timeout=2000)
            except Exception as err:
                print(f"⚠️ Target [{target_id}] interaction skipped or page shifted.")
            
            await asyncio.sleep(1.5)

        await browser.close()
        
        if not extracted_result:
            error_msg = "Mission terminated without a FINISH signal after maximum steps."
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)

        filename = f"mission_{mission_id}.json"
        result_path = os.path.join(os.path.dirname(__file__), filename)
        
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(extracted_result, f, ensure_ascii=False, indent=4)
        print(f"📦 Data Saved to {result_path}")

        for img in generated_screenshots:
            try:
                if os.path.exists(img):
                    os.remove(img)
            except Exception:
                pass

if __name__ == "__main__":
    target_goal = sys.argv[1] if len(sys.argv) > 1 else "What is the current temperature in Dehradun?"
    user_mission_id = sys.argv[2] if len(sys.argv) > 2 else "fallback"
    
    asyncio.run(run_karya_agent(target_goal, user_mission_id))
