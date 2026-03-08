"""Fetch URL and extract title, h1, first paragraph. Supports httpx and Selenium."""
import logging
from typing import Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("backend.services.parser")

# Selenium imports (optional)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    _SELENIUM_AVAILABLE = True
except ImportError:
    _SELENIUM_AVAILABLE = False


def _extract_from_html(html: str) -> Tuple[str, str, str]:
    """Из HTML извлечь title, h1, первый осмысленный абзац."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    title = (tag.get_text(strip=True) or "") if tag else ""
    h1_tag = soup.find("h1")
    h1 = (h1_tag.get_text(strip=True) or "") if h1_tag else ""
    first_paragraph = ""
    for tag in soup.find_all(["p"]):
        text = tag.get_text(strip=True)
        if len(text) > 20:
            first_paragraph = text[:1500]
            break
    return title, h1, first_paragraph


def parse_url(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Загрузка по URL через httpx и извлечение (title, h1, first_paragraph, error_message).
    """
    logger.info("parse_url (httpx): url=%s timeout=%s", url, timeout)
    headers = {"User-Agent": user_agent} if user_agent else None
    if user_agent:
        logger.debug("parse_url: using User-Agent (len=%d)", len(user_agent))
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            logger.debug("parse_url: status=%d content_len=%d", resp.status_code, len(resp.text))
            resp.raise_for_status()
            title, h1, first_paragraph = _extract_from_html(resp.text)
            logger.info("parse_url success: title_len=%d h1_len=%d paragraph_len=%d", len(title), len(h1), len(first_paragraph))
            return title, h1, first_paragraph, ""
    except httpx.TimeoutException:
        err = "Таймаут при загрузке страницы (по умолчанию 30 с). Попробуйте другой URL, увеличьте PARSER_TIMEOUT в .env или используйте Selenium (PARSER_USE_SELENIUM=true)."
        logger.warning("parse_url timeout: url=%s", url)
        return "", "", "", err
    except httpx.HTTPStatusError as e:
        err = f"Сайт вернул ошибку: {e.response.status_code}. Попробуйте другой URL."
        logger.warning("parse_url HTTP error: url=%s status=%s", url, e.response.status_code)
        return "", "", "", err
    except Exception as e:
        err = f"Не удалось загрузить страницу: {type(e).__name__}. Проверьте URL и доступность сайта."
        logger.warning("parse_url failed: url=%s error=%s", url, e)
        return "", "", "", err


def parse_url_selenium(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Загрузка по URL через Selenium (Chrome headless) для сайтов с JS.
    Возврат: (title, h1, first_paragraph, error_message).
    """
    if not _SELENIUM_AVAILABLE:
        return "", "", "", "Selenium не установлен. Установите: pip install selenium webdriver-manager"
    logger.info("parse_url_selenium: url=%s timeout=%s", url, timeout)
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        if user_agent:
            options.add_argument(f"--user-agent={user_agent}")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            html = driver.page_source
            title, h1, first_paragraph = _extract_from_html(html)
            logger.info("parse_url_selenium success: title_len=%d h1_len=%d paragraph_len=%d", len(title), len(h1), len(first_paragraph))
            return title, h1, first_paragraph, ""
        finally:
            driver.quit()
    except Exception as e:
        err = f"Selenium: {type(e).__name__} — {e}"
        logger.warning("parse_url_selenium failed: url=%s error=%s", url, e)
        return "", "", "", err


def parse_url_auto(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
    use_selenium: bool = False,
) -> tuple[str, str, str, str]:
    """
    Парсинг URL: при use_selenium=True — Selenium, иначе httpx.
    """
    if use_selenium and _SELENIUM_AVAILABLE:
        return parse_url_selenium(url, timeout=timeout, user_agent=user_agent)
    return parse_url(url, timeout=timeout, user_agent=user_agent)


def _extract_full_text(html: str, max_chars: int = 15000) -> str:
    """Извлечь весь видимый текст со страницы (для анализа контента)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    parts = []
    for tag in soup.find_all(["title", "h1", "h2", "h3", "p", "li"]):
        text = tag.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)
    result = "\n\n".join(parts)
    return result[:max_chars] if len(result) > max_chars else result


def get_url_screenshot_and_text(
    url: str,
    timeout: float = 15.0,
    user_agent: str | None = None,
) -> tuple[bytes | None, str, str, str]:
    """
    Открыть URL через Selenium, сделать скриншот и извлечь текст.
    Возврат: (screenshot_png_bytes, mime_type, extracted_text, error_message).
    При ошибке screenshot=None, error_message непустой.
    """
    if not _SELENIUM_AVAILABLE:
        return None, "image/png", "", "Selenium не установлен. Установите: pip install selenium webdriver-manager"
    logger.info("get_url_screenshot_and_text: url=%s timeout=%s", url, timeout)
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        if user_agent:
            options.add_argument(f"--user-agent={user_agent}")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            screenshot_png = driver.get_screenshot_as_png()
            html = driver.page_source
            extracted_text = _extract_full_text(html)
            logger.info("get_url_screenshot_and_text success: screenshot_len=%d text_len=%d", len(screenshot_png or []), len(extracted_text))
            return screenshot_png, "image/png", extracted_text, ""
        finally:
            driver.quit()
    except Exception as e:
        err = f"Selenium: {type(e).__name__} — {e}"
        logger.warning("get_url_screenshot_and_text failed: url=%s error=%s", url, e)
        return None, "image/png", "", err
