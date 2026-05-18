import asyncio
from playwright.async_api import async_playwright

async def run_vision_test():
    async with async_playwright() as p:
        # Launching the browser
        print("🚀 Opening browser...")
        browser = await p.chromium.launch(headless=True) # Set to False if you want to see it pop up!
        page = await browser.new_page()
        
        # Navigate to a site
        print("🌐 Navigating to Google...")
        await page.goto("https://www.google.com")
        
        # Take a screenshot - This is what we will send to Gemini later
        await page.screenshot(path="brain_vision.png")
        print("📸 Screenshot saved as 'brain_vision.png'")
        
        # Get the page title
        title = await page.title()
        print(f"📄 Page Title: {title}")
        
        await browser.close()
        print("✅ Browser test successful!")

if __name__ == "__main__":
    asyncio.run(run_vision_test())