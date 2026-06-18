"""
Action Mapper Service
---------------------
Türkçe/İngilizce natural language ↔ Selenium/Appium command mapping
"""

from typing import Dict, List, Any, Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACTION DEFINITIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ACTION_MAP = {
    # Navigation
    "navigate": {
        "tr": "Sayfaya Git",
        "en": "Navigate to",
        "params": ["url"],
        "selenium": "driver.get('{url}')",
        "appium": "driver.get('{url}')"
    },
    
    # Clicks
    "click": {
        "tr": "Tıkla",
        "en": "Click",
        "params": ["locator"],
        "selenium": "driver.find_element({locator}).click()",
        "appium": "driver.find_element({locator}).click()"
    },
    
    # Text Input
    "sendKeys": {
        "tr": "Yaz",
        "en": "Type",
        "params": ["locator", "value"],
        "selenium": "driver.find_element({locator}).send_keys('{value}')",
        "appium": "driver.find_element({locator}).send_keys('{value}')"
    },
    
    "clear": {
        "tr": "Temizle",
        "en": "Clear",
        "params": ["locator"],
        "selenium": "driver.find_element({locator}).clear()",
        "appium": "driver.find_element({locator}).clear()"
    },
    
    # Waits
    "wait": {
        "tr": "Bekle",
        
        "en": "Wait",
        "params": ["seconds"],
        "selenium": "time.sleep({seconds})",
        "appium": "time.sleep({seconds})"
    },
    
    "waitForElement": {
        "tr": "Element Görünene Kadar Bekle",
        "en": "Wait for Element",
        "params": ["locator", "timeout"],
        "selenium": "WebDriverWait(driver, {timeout}).until(EC.presence_of_element_located({locator}))",
        "appium": "WebDriverWait(driver, {timeout}).until(EC.presence_of_element_located({locator}))"
    },
    
    # Assertions
    "assertText": {
        "tr": "Metin Kontrol Et",
        "en": "Assert Text",
        "params": ["locator", "expectedText"],
        "selenium": "assert driver.find_element({locator}).text == '{expectedText}'",
        "appium": "assert driver.find_element({locator}).text == '{expectedText}'"
    },
    
    "assertVisible": {
        "tr": "Görünür Olduğunu Kontrol Et",
        "en": "Assert Visible",
        "params": ["locator"],
        "selenium": "assert driver.find_element({locator}).is_displayed()",
        "appium": "assert driver.find_element({locator}).is_displayed()"
    },
    
    # Scroll
    "scrollTo": {
        "tr": "Kaydır",
        "en": "Scroll to",
        "params": ["locator"],
        "selenium": "driver.execute_script('arguments[0].scrollIntoView();', driver.find_element({locator}))",
        "appium": "driver.execute_script('mobile: scroll', {'direction': 'down', 'element': driver.find_element({locator})})"
    },
    
    # Select (dropdown)
    "selectByText": {
        "tr": "Seç (Metin)",
        "en": "Select by Text",
        "params": ["locator", "text"],
        "selenium": "Select(driver.find_element({locator})).select_by_visible_text('{text}')",
        "appium": "Select(driver.find_element({locator})).select_by_visible_text('{text}')"
    },
    
    # Screenshots
    "screenshot": {
        "tr": "Ekran Görüntüsü Al",
        "en": "Take Screenshot",
        "params": ["filename"],
        "selenium": "driver.save_screenshot('{filename}')",
        "appium": "driver.save_screenshot('{filename}')"
    },
    
    # Mobile Specific
    "swipe": {
        "tr": "Kaydır (Mobil)",
        "en": "Swipe",
        "params": ["startX", "startY", "endX", "endY", "duration"],
        "selenium": None,
        "appium": "driver.swipe({startX}, {startY}, {endX}, {endY}, {duration})"
    },
    
    "tap": {
        "tr": "Dokun",
        "en": "Tap",
        "params": ["x", "y"],
        "selenium": None,
        "appium": "driver.tap([({x}, {y})])"
    }
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOCATOR TYPES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOCATOR_MAP = {
    "id": {
        "tr": "ID",
        "en": "ID",
        "selenium": "By.ID, '{value}'",
        "appium": "AppiumBy.ID, '{value}'"
    },
    "xpath": {
        "tr": "XPath",
        "en": "XPath",
        "selenium": "By.XPATH, '{value}'",
        "appium": "AppiumBy.XPATH, '{value}'"
    },
    "css": {
        "tr": "CSS Selector",
        "en": "CSS Selector",
        "selenium": "By.CSS_SELECTOR, '{value}'",
        "appium": "AppiumBy.CSS_SELECTOR, '{value}'"
    },
    "name": {
        "tr": "Name",
        "en": "Name",
        "selenium": "By.NAME, '{value}'",
        "appium": "AppiumBy.NAME, '{value}'"
    },
    "class": {
        "tr": "Class Name",
        "en": "Class Name",
        "selenium": "By.CLASS_NAME, '{value}'",
        "appium": "AppiumBy.CLASS_NAME, '{value}'"
    },
    "linkText": {
        "tr": "Link Text",
        "en": "Link Text",
        "selenium": "By.LINK_TEXT, '{value}'",
        "appium": "AppiumBy.LINK_TEXT, '{value}'"
    },
    "accessibility": {
        "tr": "Accessibility ID",
        "en": "Accessibility ID",
        "selenium": None,
        "appium": "AppiumBy.ACCESSIBILITY_ID, '{value}'"
    }
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONVERSION FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def action_to_display(action: str, lang: str = "tr") -> str:
    """
    Action kodunu display text'e çevir.
    
    Args:
        action: Selenium action kodu (örn: "click")
        lang: Dil kodu ("tr" veya "en")
    
    Returns:
        Display text (örn: "Tıkla" veya "Click")
    """
    if action in ACTION_MAP:
        return ACTION_MAP[action].get(lang, action)
    return action


def display_to_action(display_text: str, lang: str = "tr") -> Optional[str]:
    """
    Display text'i action koduna çevir.
    
    Args:
        display_text: UI'da gösterilen text (örn: "Tıkla")
        lang: Dil kodu ("tr" veya "en")
    
    Returns:
        Action kodu (örn: "click")
    """
    for action_code, action_data in ACTION_MAP.items():
        if action_data.get(lang, "").lower() == display_text.lower():
            return action_codebu 
    return None


def step_to_display(step: Dict[str, Any], lang: str = "tr") -> str:
    """
    JSON step'i human-readable text'e çevir.
    
    Args:
        step: {"action": "sendKeys", "locator": {...}, "value": "admin"}
        lang: Dil kodu
    
    Returns:
        "Yaz: admin (id: username)" veya "Type: admin (id: username)"
    """
    action = step.get("action", "")
    action_display = action_to_display(action, lang)
    
    # Parametreleri topla
    parts = [action_display]
    
    if "url" in step:
        parts.append(f": {step['url']}")
    
    if "value" in step:
        parts.append(f": {step['value']}")
    
    if "locator" in step:
        loc = step["locator"]
        loc_type = loc.get("type", "")
        loc_value = loc.get("value", "")
        parts.append(f" ({loc_type}: {loc_value})")
    
    if "seconds" in step:
        parts.append(f" ({step['seconds']}s)")
    
    return "".join(parts)


def get_available_actions(lang: str = "tr", filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Kullanılabilir action'ları listele.
    
    Args:
        lang: Dil kodu
        filter_type: "web", "mobile" veya None (hepsi)
    
    Returns:
        [{"code": "click", "display": "Tıkla", "params": [...]}]
    """
    actions = []
    
    for code, data in ACTION_MAP.items():
        # Mobile filter
        if filter_type == "mobile" and data.get("appium") is None:
            continue
        
        # Web filter
        if filter_type == "web" and data.get("selenium") is None:
            continue
        
        actions.append({
            "code": code,
            "display": data.get(lang, code),
            "params": data.get("params", [])
        })
    
    return actions


def get_locator_types(lang: str = "tr") -> List[Dict[str, str]]:
    """
    Locator tiplerini listele.
    
    Returns:
        [{"code": "id", "display": "ID"}]
    """
    return [
        {"code": code, "display": data.get(lang, code)}
        for code, data in LOCATOR_MAP.items()
    ]


def validate_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step'i validate et.
    
    Returns:
        {"valid": bool, "errors": [...]}
    """
    errors = []
    
    action = step.get("action")
    if not action:
        errors.append("Action eksik")
        return {"valid": False, "errors": errors}
    
    if action not in ACTION_MAP:
        errors.append(f"Geçersiz action: {action}")
        return {"valid": False, "errors": errors}
    
    # Required parametreleri kontrol et
    required_params = ACTION_MAP[action].get("params", [])
    
    for param in required_params:
        if param == "locator":
            if "locator" not in step:
                errors.append(f"Locator eksik")
            elif not isinstance(step["locator"], dict):
                errors.append("Locator bir dict olmalı")
            elif "type" not in step["locator"] or "value" not in step["locator"]:
                errors.append("Locator'da type ve value olmalı")
        else:
            if param not in step:
                errors.append(f"Parametre eksik: {param}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXPORT FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_selenium_code(steps: List[Dict[str, Any]], lang: str = "python") -> str:
    """
    JSON steps'lerden Selenium kodu üret.
    
    Returns:
        Python Selenium kodu
    """
    lines = [
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "from selenium.webdriver.support.select import Select",
        "import time",
        "",
        "# Initialize driver",
        "driver = webdriver.Chrome()",
        "driver.maximize_window()",
        "",
        "try:"
    ]
    
    for step in steps:
        action = step.get("action", "")
        if action not in ACTION_MAP:
            continue
        
        template = ACTION_MAP[action].get("selenium")
        if not template:
            continue
        
        # Locator dönüşümü
        code_line = template
        if "locator" in step:
            loc = step["locator"]
            loc_type = loc.get("type", "id")
            loc_value = loc.get("value", "")
            
            locator_template = LOCATOR_MAP.get(loc_type, {}).get("selenium", "By.ID, '{value}'")
            locator_code = locator_template.format(value=loc_value)
            code_line = code_line.replace("{locator}", locator_code)
        
        # Diğer parametreler
        for key, value in step.items():
            if key not in ["action", "locator"]:
                code_line = code_line.replace(f"{{{key}}}", str(value))
        
        lines.append(f"    {code_line}")
    
    lines.extend([
        "",
        "finally:",
        "    driver.quit()"
    ])
    
    return "\n".join(lines)