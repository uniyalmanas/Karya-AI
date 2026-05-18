import os
import asyncio
import json
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def clean_json(text):
    return re.sub(r'```json|```', '', text).strip()

async def run_karya_agent(goal):
    async with async_playwright() as p:
        print(f"🎯 Mission: {goal}")
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://duckduckgo.com", wait_until="networkidle")
        
        extracted_result = None

        for i in range(7):
            print(f"\n--- Step {i+1} ---")
            await page.screenshot(path="current_state.png")
            with open("current_state.png", "rb") as f:
                img_data = f.read()

            # We define exactly what the JSON must look like
            prompt = f"Goal: {goal}. Analyze the screenshot. Use 'FINISH' only when data is found."

            response = client.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=[prompt, types.Part.from_bytes(data=img_data, mime_type="image/png")],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    # THIS IS THE GUARD: It defines the exact keys allowed
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "thought": {"type": "STRING"},
                            "action": {"type": "STRING", "enum": ["CLICK", "TYPE", "FINISH"]},
                            "selector": {"type": "STRING"},
                            "text": {"type": "STRING"},
                            "extracted_data": {
                                "type": "OBJECT",
                                "properties": {
                                    "answer": {"type": "STRING"},
                                    "source": {"type": "STRING"}
                                }
                            }
                        },
                        "required": ["thought", "action"]
                    }
                )
            )

            res = json.loads(clean_json(response.text))
            print(f"💭 AI Thought: {res['thought']}")

            # Check if the AI actually gave us data when it finished
            if res['action'] == "FINISH":
                # If Gemini was lazy, we look in the 'thought' to rescue the data
                extracted_result = res.get('extracted_data')
                if not extracted_result or not extracted_result.get('answer'):
                    print("🛠️ Rescuing data from AI thought...")
                    extracted_result = {"answer": res['thought']}
                
                print("🏁 Mission Accomplished!")
                break
            
            elif res['action'] == "TYPE":
                await page.fill(res['selector'], res['text'])
                await page.keyboard.press("Enter")
            elif res['action'] == "CLICK":
                await page.click(res['selector'])
            
            await asyncio.sleep(3)

        await browser.close()

        if extracted_result:
            with open("mission_result.json", "w") as f:
                json.dump(extracted_result, f, indent=4)
            print(f"📦 Data Saved: {extracted_result}")

if __name__ == "__main__":
    asyncio.run(run_karya_agent("What is the current temperature in Dehradun?"))