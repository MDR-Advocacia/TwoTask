from playwright.sync_api import sync_playwright, expect
import re

def run_final_verification(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Navigate to the application
        page.goto("http://127.0.0.1:8080/")

        # Wait for the main dashboard to load
        expect(page.get_by_role("button", name="Dashboard")).to_be_visible(timeout=15000)

        # 2. Click the "Criar Tarefas" tab
        page.get_by_role("button", name="Criar Tarefas", exact=True).click()

        # 3. Wait for 5 seconds to allow the component to render or fail
        print("Waiting for component to render...")
        page.wait_for_timeout(5000)

        # 4. Take the final screenshot for visual confirmation
        page.screenshot(path="jules-scratch/verification/final_verification.png")

        print("Final verification screenshot captured.")

    except Exception as e:
        print(f"An error occurred during final verification: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
    finally:
        browser.close()

with sync_playwright() as playwright:
    run_final_verification(playwright)