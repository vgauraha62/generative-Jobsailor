import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _dump_state(driver, tag: str) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    info = {"tag": tag, "ts": ts}
    try:
        src = driver.page_source or ""
        info["page_snippet"] = src[-1200:]
        alerts = driver.find_elements(By.XPATH, "//*[contains(@class,'alert') or contains(@class,'toast') or contains(@class,'error') or contains(@class,'message')]")
        info["alerts"] = [a.text.strip() for a in alerts if a.text.strip()][:5]
    except Exception as e:
        info["alerts_error"] = str(e)
    try:
        path = f"reports/upload_{tag}_{ts}.png"
        Path("reports").mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(path)
        info["screenshot"] = path
    except Exception as e:
        info["screenshot_error"] = str(e)
    return info


def upload_to_naukri(driver, pdf_path: str, timeout=25) -> tuple:
    pdf_abs = os.path.abspath(pdf_path)
    if not os.path.exists(pdf_abs):
        print(f"[upload] file not found: {pdf_abs}")
        return False, {"step": "validate", "error": "file_not_found", "path": pdf_abs}
    size = os.path.getsize(pdf_abs)
    if size > 2 * 1024 * 1024:
        print(f"[upload] file too large {size} bytes, >2MB")
        return False, {"step": "validate", "error": "file_too_large", "size": size}
    if size == 0:
        return False, {"step": "validate", "error": "file_empty"}

    driver.get("https://www.naukri.com/mnjuser/profile")
    time.sleep(4)

    for attempt in range(2):
        try:
            try:
                update_btns = driver.find_elements(By.XPATH, "//button[contains(translate(normalize-space(.),'UPDATE','update'),'update resume') or contains(translate(normalize-space(.),'UPDATE','update'),'update')]")
                for b in update_btns:
                    try:
                        if b.is_displayed():
                            driver.execute_script("arguments[0].click();", b)
                            time.sleep(1.5)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            inp = None
            outer = None
            candidates = [
                "//input[@id='attachCV']",
                "//input[contains(@id,'attachCV')]",
                "//input[@type='file' and contains(@id,'resume')]",
                "//input[@type='file']",
                "//input[contains(@id,'resume')]",
            ]
            for xp in candidates:
                try:
                    els = driver.find_elements(By.XPATH, xp)
                    if els:
                        inp = els[0]
                        try:
                            outer = inp.get_attribute("outerHTML")[:1200]
                        except Exception:
                            outer = None
                        break
                except Exception:
                    continue
            if inp is None:
                try:
                    inp = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                    try:
                        outer = inp.get_attribute("outerHTML")[:1200]
                    except Exception:
                        pass
                except Exception as e:
                    info = _dump_state(driver, f"no_input_a{attempt+1}")
                    info.update({"step": "find_input", "attempt": attempt+1, "outerHTML": outer, "error": str(e), "traceback": traceback.format_exc()[:3000]})
                    print(f"[upload] file input not found attempt {attempt+1}")
                    if attempt == 1:
                        return False, info
                    time.sleep(2)
                    continue

            try:
                if not inp.is_displayed():
                    driver.execute_script("arguments[0].style.display='block'; arguments[0].style.visibility='visible'; arguments[0].style.opacity='1';", inp)
                    time.sleep(0.5)
            except Exception:
                pass

            try:
                inp.send_keys(pdf_abs)
            except Exception as e:
                info = _dump_state(driver, f"send_keys_a{attempt+1}")
                info.update({"step": "send_keys", "attempt": attempt+1, "outerHTML": outer, "error": str(e), "traceback": traceback.format_exc()[:3000]})
                print(f"[upload] send_keys failed attempt {attempt+1}: {e}")
                if attempt == 1:
                    return False, info
                time.sleep(2)
                continue

            try:
                WebDriverWait(driver, timeout).until(
                    lambda d: any(x in (d.page_source or "").lower() for x in ["successfully", "uploaded", "resume has been"])
                )
                info = _dump_state(driver, f"success_a{attempt+1}")
                info.update({"step": "wait_success", "attempt": attempt+1, "outerHTML": outer})
                return True, info
            except Exception as e:
                info = _dump_state(driver, f"wait_a{attempt+1}")
                alerts = info.get("alerts", [])
                generic_error = any("error" in (a or "").lower() for a in alerts)
                info.update({"step": "wait_success", "attempt": attempt+1, "outerHTML": outer, "error": str(e)[:400], "traceback": traceback.format_exc()[:3000], "generic_error": generic_error})
                lower_src = (driver.page_source or "").lower()
                if "uploaded" in lower_src or "successfully" in lower_src:
                    return True, info
                if attempt == 1:
                    print(f"[upload] wait failed, page alerts: {alerts}")
                    return False, info
                time.sleep(3)
                continue

        except Exception as e:
            info = _dump_state(driver, f"outer_a{attempt+1}")
            info.update({"step": "outer", "attempt": attempt+1, "error": str(e), "traceback": traceback.format_exc()[:3000]})
            if attempt == 1:
                return False, info
            time.sleep(2)
            continue

    return False, {"step": "exhausted", "error": "retries_exhausted"}
