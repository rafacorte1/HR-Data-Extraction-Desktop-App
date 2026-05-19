# -*- coding: utf-8 -*-
"""
Generic helpers: time formatting and Selenium DOM synchronization utilities.

These helpers are intentionally framework-agnostic so they can be reused
across different scraping projects targeting JS-heavy enterprise apps
(Angular / JSF / PrimeFaces / etc.).
"""

import time
from time import sleep

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


def format_hms(seconds: float) -> str:
    """Format seconds as HH:MM:SS (or MM:SS if under an hour)."""
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def wait_for_page_ready(driver: webdriver.Chrome, timeout: int = 20) -> None:
    """Wait until document.readyState === 'complete'."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def dom_has_blocking_overlay(driver: webdriver.Chrome) -> bool:
    """
    Heuristic to detect common loading overlays in enterprise web apps.
    Adjust selectors below to match your target system if needed.
    """
    try:
        overlays = driver.find_elements(
            By.CSS_SELECTOR,
            ".ui-blockui-mask, .ui-dialog-mask, .loading, .spinner, .overlay, "
            "[sp-loading-mask]",
        )
        return any(ov.is_displayed() for ov in overlays)
    except Exception:
        return False


def wait_for_dom_idle(
    driver: webdriver.Chrome, timeout: int = 20, poll_every: float = 0.25
) -> None:
    """
    Wait until no blocking overlays are visible for N consecutive checks.
    Prevents premature interaction with elements still being rendered.
    """
    end = time.time() + timeout
    consecutive_clear_needed = 4
    clear_count = 0
    while time.time() < end:
        if not dom_has_blocking_overlay(driver):
            clear_count += 1
            if clear_count >= consecutive_clear_needed:
                return
        else:
            clear_count = 0
        sleep(poll_every)


def wait_and_pause(
    driver: webdriver.Chrome,
    locator: tuple,
    timeout: int = 20,
    pause_after: float = 0.25,
):
    """
    Wait for an element to be visible (and clickable if possible), then
    apply a short cushion pause before returning it.
    """
    el = WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located(locator)
    )
    try:
        WebDriverWait(driver, max(2, int(timeout / 3))).until(
            EC.element_to_be_clickable(locator)
        )
    except TimeoutException:
        pass
    sleep(pause_after)
    return el


def click_with_fallback(
    driver: webdriver.Chrome,
    locator: str,
    by: str = By.XPATH,
    timeout: int = 20,
):
    """
    Click an element with a JavaScript-click fallback for elements that
    are covered by overlays or otherwise non-clickable via standard means.
    """
    wait = WebDriverWait(driver, timeout)
    try:
        el = wait.until(EC.element_to_be_clickable((by, locator)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        return el
    except Exception:
        el = wait.until(EC.visibility_of_element_located((by, locator)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        driver.execute_script("arguments[0].click();", el)
        return el


def type_text_safely(
    element,
    text: str,
    validate: bool = True,
    retries: int = 2,
    pause_after: float = 0.15,
) -> None:
    """Type into an input and optionally validate the resulting value."""
    element.clear()
    element.send_keys(text)
    sleep(pause_after)
    if not validate:
        return

    try:
        val = element.get_attribute("value") or element.get_attribute("innerText") or ""
    except Exception:
        val = ""

    if val.strip() != text.strip() and retries > 0:
        element.clear()
        element.send_keys(text)
        sleep(pause_after)