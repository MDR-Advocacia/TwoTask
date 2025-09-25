# jules-scratch/verification/verify_squad_management.py

from playwright.sync_api import sync_playwright, Page, expect

def run_verification(page: Page):
    """
    Automates the verification of the new squad and sector management UI.
    """
    # 1. Navigate to the Admin Page
    # The dev server runs on 5173 as per the docker-compose and vite config.
    page.goto("http://localhost:5173/admin")

    # --- Step 2: Create a new Sector ---
    page.get_by_role("button", name="Novo Setor").click()

    # Fill in the sector name in the dialog
    expect(page.get_by_role("heading", name="Novo Setor")).to_be_visible()
    page.get_by_label("Nome").fill("Tributário")
    page.get_by_role("button", name="Salvar").click()

    # Verify the new sector appears in the table
    expect(page.get_by_role("cell", name="Tributário")).to_be_visible()

    # --- Step 3: Create a new Squad ---
    page.get_by_role("button", name="Novo Squad").click()

    # Fill in the squad details in the dialog
    expect(page.get_by_role("heading", name="Novo Squad")).to_be_visible()
    page.get_by_label("Nome").fill("Equipe Fiscal")

    # Select the sector we just created
    page.get_by_label("Setor").click()
    page.get_by_role("option", name="Tributário").click()

    # Select members and assign a leader
    # Assuming 'Usuário 1' and 'Usuário 2' exist from the backend sync
    page.get_by_label("Usuário 1").check()
    page.get_by_label("Usuário 2").check()

    # Make 'Usuário 1' the leader
    page.locator('div').filter(has_text="Usuário 1Líder").get_by_role('checkbox').nth(1).check()

    # Save the squad
    page.get_by_role("button", name="Salvar Squad").click()

    # --- Step 4: Verify the new Squad appears ---
    expect(page.get_by_role("cell", name="Equipe Fiscal")).to_be_visible()
    # Check that the leader badge is visible for the correct user
    leader_badge = page.locator('//td[text()="Equipe Fiscal"]/following-sibling::td[2]//span[contains(text(), "Usuário 1")]/preceding-sibling::svg')
    expect(leader_badge).to_be_visible()

    # --- Step 5: Take a screenshot ---
    page.screenshot(path="jules-scratch/verification/squad_management_verification.png", full_page=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        run_verification(page)
        browser.close()

if __name__ == "__main__":
    main()