# -*- coding: utf-8 -*-
"""
Centralized configuration loaded from environment variables.
Copy `.env.example` to `.env` and customize for your target system.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Target system
URL_HOME = os.getenv("TARGET_URL", "https://example.com/home")

# DOM selectors (override via .env to match your target system)
XPATH_MANAGE_ACCOUNTS = os.getenv(
    "MANAGE_CARD_XPATH",
    "//div[contains(@class,'card-title') and normalize-space(.)='Manage Accounts']",
)
ID_SEARCH_INPUT = os.getenv("SEARCH_INPUT_ID", "searchInput")
ID_SEARCH_BUTTON = os.getenv("SEARCH_BUTTON_ID", "searchBtn")
ID_TAB_ATTRIBUTES = os.getenv("ATTRIBUTES_TAB_ID", "nav-identity-attributes")
ID_TABLE_ATTRIBUTES = os.getenv(
    "ATTRIBUTES_TABLE_ID", "identity-attributes-data-table-container"
)

# Timing
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))