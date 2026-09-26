from selenium.webdriver.common.by import By


def extract_jd(driver) -> str:
    selectors = [
        "//div[contains(@class,'styles_JDC__dang-inner-html')]",
        "//div[contains(@class,'styles_job-desc')]",
        "//div[contains(@class,'dang-inner-html')]",
        "//section[contains(@class,'job-desc')]",
        "//div[contains(@class,'job-desc')]",
    ]
    for xp in selectors:
        els = driver.find_elements(By.XPATH, xp)
        for el in els:
            t = (el.text or "").strip()
            if len(t) > 100:
                return t
    body_text = (driver.find_element(By.TAG_NAME, "body").text or "").strip()
    return body_text[:8000]


def has_surface(driver) -> str:
    chat = driver.find_elements(By.XPATH, "//ul[contains(@id,'chatList_')]")
    radio = driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container")
    form = driver.find_elements(By.CSS_SELECTOR, "[class*='form-field'], [class*='formField'], [class*='styles_form-box']")
    has_chat = bool(chat or radio)
    has_form = bool(form)
    if has_chat and has_form:
        return "both"
    if has_chat:
        return "chat_widget"
    if has_form:
        return "full_form"
    return "none"
