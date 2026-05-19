# -*- coding: utf-8 -*-
"""
Selenium workflow for extracting employee identity attributes from a
web-based HR/Identity Management system.

Pipeline per employee:
    1. Navigate to home
    2. Open the "Manage Accounts" card
    3. Search the employee by name
    4. Click the "Manage" action for that employee
    5. Open the Identity Attributes tab
    6. Extract the (Attribute, Value) table into a DataFrame
"""

from time import sleep

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from src.config import (
    URL_HOME,
    XPATH_MANAGE_ACCOUNTS,
    ID_SEARCH_INPUT,
    ID_SEARCH_BUTTON,
    ID_TAB_ATTRIBUTES,
    ID_TABLE_ATTRIBUTES,
    DEFAULT_TIMEOUT,
)
from src.utils import (
    wait_for_page_ready,
    wait_for_dom_idle,
    wait_and_pause,
    click_with_fallback,
    type_text_safely,
)


def init_driver(headless: bool = False) -> webdriver.Chrome:
    """Initialize Chrome WebDriver using Selenium Manager (auto-driver)."""
    options = Options()
    options.add_argument("--window-size=1400,900")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(2)
    return driver


def wait_identity_attributes_loaded(
    driver: webdriver.Chrome, timeout: int = 20
) -> bool:
    """Wait until the attributes table has rendered at least one row."""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, ID_TABLE_ATTRIBUTES))
    )
    WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located(
            (
                By.XPATH,
                f"//table[@id='{ID_TABLE_ATTRIBUTES}']//tr[.//th and .//td]",
            )
        )
    )
    return True


def extract_identity_attributes(driver: webdriver.Chrome) -> pd.DataFrame:
    """Extract the (Attribute, Value) key-value table into a DataFrame."""
    wait_identity_attributes_loaded(driver, timeout=30)
    rows = driver.find_elements(
        By.XPATH,
        f"//table[@id='{ID_TABLE_ATTRIBUTES}']//tr[.//th and .//td]",
    )

    data = []
    for row in rows:
        try:
            th_el = row.find_element(By.XPATH, ".//th")
            td_el = row.find_element(By.XPATH, ".//td")
            key = (th_el.get_attribute("innerText") or th_el.text or "").strip()
            value = (td_el.get_attribute("innerText") or td_el.text or "").strip()
            if key and value:
                data.append({"Attribute": key, "Value": value})
        except Exception:
            continue

    return pd.DataFrame(data)


def click_manage_for_user(
    driver: webdriver.Chrome, user_name: str, timeout: int = 20
) -> None:
    """
    Click the 'Manage' action for the row matching the given user name,
    using a cascade of strategies (aria-label → row-context → first visible).
    """
    wait = WebDriverWait(driver, timeout)

    # Ensure result rows have rendered
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[self::tr or self::div][.//text()[normalize-space()!='']]",
                )
            )
        )
    except TimeoutException:
        pass

    # Strategy A: generic aria-label
    try:
        el = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(@aria-label, 'Manage Accounts') "
                    "or contains(@aria-label, 'Manage Account')]",
                )
            )
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        return
    except Exception:
        pass

    # Strategy B: 'Manage' button/link inside the row containing the user name
    try:
        xp_row = (
            "//*[self::tr or self::div]["
            "contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÄËÏÖÜÂÊÎÔÛÀÈÌÒÙÇÑ', "
            "'abcdefghijklmnopqrstuvwxyzáéíóúäëïöüâêîôûàèìòùçñ'), "
            f"'{user_name.lower()}')]"
        )
        xp_manage_in_row = (
            f"{xp_row}//button[normalize-space()='Manage' or contains(., 'Manage')] | "
            f"{xp_row}//a[normalize-space()='Manage' or contains(., 'Manage')]"
        )
        el = wait.until(EC.element_to_be_clickable((By.XPATH, xp_manage_in_row)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        return
    except Exception:
        pass

    # Strategy C: first visible 'Manage' on the page
    try:
        el = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[normalize-space()='Manage' or contains(., 'Manage')] | "
                    "//a[normalize-space()='Manage' or contains(., 'Manage')]",
                )
            )
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()
        return
    except Exception:
        pass

    raise TimeoutException(
        f"Could not locate/click the 'Manage' button for '{user_name}'."
    )


def scrape_user(
    driver: webdriver.Chrome, user_name: str, timeout: int = DEFAULT_TIMEOUT
) -> pd.DataFrame:
    """End-to-end navigation and extraction for a single user."""
    # 1) Home
    driver.get(URL_HOME)
    wait_for_page_ready(driver, timeout=timeout)
    wait_for_dom_idle(driver, timeout=min(6, timeout))

    # 2) 'Manage Accounts' card
    click_with_fallback(driver, XPATH_MANAGE_ACCOUNTS, by=By.XPATH, timeout=timeout)
    wait_for_page_ready(driver, timeout=timeout)
    wait_for_dom_idle(driver, timeout=min(6, timeout))
    sleep(0.2)

    # 3) Search by name
    search = wait_and_pause(
        driver, (By.ID, ID_SEARCH_INPUT), timeout=timeout, pause_after=0.2
    )
    type_text_safely(search, user_name, validate=True, retries=2, pause_after=0.15)

    wait_and_pause(driver, (By.ID, ID_SEARCH_BUTTON), timeout=timeout, pause_after=0.1)
    click_with_fallback(driver, ID_SEARCH_BUTTON, by=By.ID, timeout=timeout)

    try:
        WebDriverWait(driver, max(5, int(timeout / 2))).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[self::tr or self::div][.//text()[normalize-space()!='']]",
                )
            )
        )
    except TimeoutException:
        pass

    wait_for_page_ready(driver, timeout=timeout)
    wait_for_dom_idle(driver, timeout=min(8, timeout))
    sleep(0.3)

    # 4) 'Manage' button (robust)
    click_manage_for_user(driver, user_name, timeout=timeout)
    wait_for_page_ready(driver, timeout=timeout)
    wait_for_dom_idle(driver, timeout=min(6, timeout))
    sleep(0.2)

    # 5) Open 'Identity Attributes' tab and extract
    click_with_fallback(driver, ID_TAB_ATTRIBUTES, by=By.ID, timeout=timeout)
    wait_for_page_ready(driver, timeout=timeout)
    wait_for_dom_idle(driver, timeout=min(6, timeout))
    sleep(0.2)

    return extract_identity_attributes(driver)