"""Fetch a URL and extract title/h1/first paragraph (or a screenshot), via httpx or Selenium.

Outbound safety: every URL is validated with backend.services.url_safety before
any network access (SSRF guard — see that module's docstring). For the httpx
flow, each redirect hop is re-validated before being followed, so a public URL
that redirects to a private/internal address is rejected. For Selenium, only
the initial destination is validated: Selenium does not expose per-hop redirect
control, and this tool does not attempt to build a full network sandbox around
it — only trusted/public competitor URLs are supported for the URL-analysis
feature (POST /analyze_url).
"""
import logging
from dataclasses import dataclass
from typing import Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from backend.errors import UnsupportedMediaTypeError, UpstreamError, UpstreamTimeoutError
from backend.services.url_safety import UnsafeURLError, redact_url, validate_public_http_url

logger = logging.getLogger("backend.services.parser")

# Selenium imports (optional). Driver binaries are resolved by Selenium Manager
# (built into selenium>=4.6), not by the legacy webdriver-manager downloader.
try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException as _SeleniumTimeoutException
    from selenium.webdriver.chrome.options import Options
    _SELENIUM_AVAILABLE = True
except ImportError:
    _SeleniumTimeoutException = None
    _SELENIUM_AVAILABLE = False

TEXT_LIKE_CONTENT_TYPES_PREFIXES = ("text/",)
TEXT_LIKE_CONTENT_TYPES_EXACT = ("application/xhtml+xml", "application/xml")

# Sanitized, stable messages returned to callers on Selenium failure — never the raw
# webdriver/Selenium exception text (which can include local paths, driver internals, etc.).
# Full exception detail always goes to the server log at the point of failure instead. Callers
# compare against these constants (or the "таймаут" substring, consistent with the httpx path's
# own timeout message) to map to the correct HTTP status — see backend.routers.analyze_url and
# backend.routers.parse_demo.
SELENIUM_NOT_INSTALLED_MESSAGE = "Selenium не установлен. Установите: pip install selenium"
SELENIUM_TIMEOUT_MESSAGE = "Таймаут при загрузке страницы через Selenium."
SELENIUM_UPSTREAM_ERROR_MESSAGE = "Не удалось загрузить страницу через Selenium."

# Cap on the raw Selenium page_source we run through BeautifulSoup / send onward. Selenium has
# no equivalent of httpx's streaming byte cap (the browser fetches the page internally; this
# tool doesn't intercept its network layer — see docs.md), so this bounds our own processing
# and downstream AI input by truncating the already-fetched page source string. Reuses
# Settings.max_remote_response_bytes (the app's one "how much of a fetched page do we process"
# limit) as a character count — an approximation, since page_source is already decoded text by
# the time we can see it, but close enough to serve the same purpose as the httpx byte cap.
DEFAULT_MAX_PAGE_SOURCE_CHARS = 5 * 1024 * 1024


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


def _is_text_like(content_type: str) -> bool:
    if not content_type:
        return True  # отсутствующий заголовок — не отклоняем, парсим как текст
    ct = content_type.split(";")[0].strip().lower()
    return ct.startswith(TEXT_LIKE_CONTENT_TYPES_PREFIXES) or ct in TEXT_LIKE_CONTENT_TYPES_EXACT


@dataclass
class _FetchedPage:
    text: str
    status_code: int
    final_url: str


def _fetch_safely(
    url: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    user_agent: str | None,
    max_redirects: int,
    max_response_bytes: int,
    transport: httpx.BaseTransport | None = None,
    resolver=None,
) -> _FetchedPage:
    """GET a URL over httpx, validating the destination and every redirect hop,
    and capping the amount of response body read into memory.

    `transport` and `resolver` are test-injection points (see tests/test_parser_service.py) —
    production callers leave them as None (real network, real DNS)."""
    headers = {"User-Agent": user_agent} if user_agent else None
    timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=connect_timeout, pool=connect_timeout)
    current_url = url
    resolver_kwargs = {"resolver": resolver} if resolver is not None else {}

    with httpx.Client(follow_redirects=False, timeout=timeout, transport=transport) as client:
        for _hop in range(max_redirects + 1):
            try:
                validate_public_http_url(current_url, **resolver_kwargs)
            except UnsafeURLError as e:
                raise UpstreamError(str(e), log_message=f"unsafe redirect target: {redact_url(current_url)}") from e

            try:
                with client.stream("GET", current_url, headers=headers) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        resp.close()
                        if not location:
                            raise UpstreamError("Сайт вернул редирект без адреса назначения.")
                        current_url = urljoin(current_url, location)
                        continue

                    content_type = resp.headers.get("content-type") or ""
                    if not _is_text_like(content_type):
                        resp.close()
                        raise UnsupportedMediaTypeError(
                            f"Сайт вернул неподдерживаемый тип контента: {content_type or 'unknown'}."
                        )

                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            resp.close()
                            raise UpstreamError(
                                f"Ответ сайта превышает допустимый размер ({max_response_bytes} байт)."
                            )
                    # header-only charset lookup (safe to call without having fully read the
                    # body via httpx's higher-level .text/.encoding, which can raise on streams)
                    encoding = resp.charset_encoding or "utf-8"
                    text = bytes(body).decode(encoding, errors="replace")
                    return _FetchedPage(text=text, status_code=resp.status_code, final_url=current_url)
            except httpx.TimeoutException as e:
                raise UpstreamTimeoutError(
                    "Таймаут при загрузке страницы. Попробуйте другой URL, увеличьте PARSER_TIMEOUT "
                    "или используйте Selenium (PARSER_USE_SELENIUM=true).",
                    log_message=f"timeout fetching {redact_url(current_url)}: {e}",
                ) from e
            except httpx.HTTPError as e:
                raise UpstreamError(
                    "Не удалось загрузить страницу. Проверьте URL и доступность сайта.",
                    log_message=f"httpx error fetching {redact_url(current_url)}: {e}",
                ) from e

        raise UpstreamError("Слишком много редиректов.", log_message=f"too many redirects from {redact_url(url)}")


def parse_url(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
    *,
    connect_timeout: float = 10.0,
    max_redirects: int = 5,
    max_response_bytes: int = 5 * 1024 * 1024,
    transport: httpx.BaseTransport | None = None,
    resolver=None,
) -> tuple[str, str, str, str]:
    """
    Загрузка по URL через httpx и извлечение (title, h1, first_paragraph, error_message).
    error_message непустой при обычной ошибке загрузки/парсинга (сохранено для эндпоинтов,
    которые исторически возвращают текст ошибки как значение, а не исключение — см.
    backend.routers.parse_demo, в т.ч. логика повтора с Selenium). Небезопасный URL (см.
    backend.services.url_safety) — это отдельный класс ошибки и пробрасывается как
    UnsafeURLError, чтобы вызывающий код мог вернуть корректный 400, а не пытаться повторить
    запрос. `transport`/`resolver` — точки внедрения для тестов (реальные вызовы их не задают).
    """
    logger.info("parse_url (httpx): url=%s timeout=%s", redact_url(url), timeout)
    resolver_kwargs = {"resolver": resolver} if resolver is not None else {}
    validate_public_http_url(url, **resolver_kwargs)
    try:
        page = _fetch_safely(
            url,
            connect_timeout=connect_timeout,
            read_timeout=timeout,
            user_agent=user_agent,
            max_redirects=max_redirects,
            max_response_bytes=max_response_bytes,
            transport=transport,
            resolver=resolver,
        )
    except (UpstreamError, UpstreamTimeoutError, UnsupportedMediaTypeError) as e:
        return "", "", "", e.message
    if page.status_code >= 400:
        err = f"Сайт вернул ошибку: {page.status_code}. Попробуйте другой URL."
        logger.warning("parse_url HTTP error: url=%s status=%s", redact_url(url), page.status_code)
        return "", "", "", err
    title, h1, first_paragraph = _extract_from_html(page.text)
    logger.info(
        "parse_url success: title_len=%d h1_len=%d paragraph_len=%d", len(title), len(h1), len(first_paragraph)
    )
    return title, h1, first_paragraph, ""


def _build_chrome_options(user_agent: str | None, *, allow_no_sandbox: bool) -> "Options":
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if allow_no_sandbox:
        # Небезопасный флаг, отключающий песочницу Chrome. Только для явно заданных
        # ограниченных сред (SELENIUM_ALLOW_NO_SANDBOX=true) — не для обычного использования.
        options.add_argument("--no-sandbox")
        logger.warning("Selenium: chrome sandbox disabled via SELENIUM_ALLOW_NO_SANDBOX (opt-in, insecure).")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    return options


def _new_chrome_driver(user_agent: str | None, *, allow_no_sandbox: bool = False):
    """Construct a Chrome WebDriver. Driver binary resolution is delegated to Selenium
    Manager (built into selenium, no webdriver-manager network download at runtime)."""
    options = _build_chrome_options(user_agent, allow_no_sandbox=allow_no_sandbox)
    return webdriver.Chrome(options=options)


def parse_url_selenium(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
    *,
    allow_no_sandbox: bool = False,
    max_page_source_chars: int = DEFAULT_MAX_PAGE_SOURCE_CHARS,
) -> tuple[str, str, str, str]:
    """
    Загрузка по URL через Selenium (Chrome headless) для сайтов с JS.
    Возврат: (title, h1, first_paragraph, error_message) — error_message, если непустой,
    это стабильное санитизированное сообщение (SELENIUM_*_MESSAGE выше), никогда сырой текст
    исключения webdriver; полная информация для диагностики уходит только в серверный лог.
    """
    if not _SELENIUM_AVAILABLE:
        return "", "", "", SELENIUM_NOT_INSTALLED_MESSAGE
    validate_public_http_url(url)
    logger.info("parse_url_selenium: url=%s timeout=%s", redact_url(url), timeout)
    driver = None
    try:
        driver = _new_chrome_driver(user_agent, allow_no_sandbox=allow_no_sandbox)
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        html = driver.page_source
        if len(html) > max_page_source_chars:
            html = html[:max_page_source_chars]
        title, h1, first_paragraph = _extract_from_html(html)
        logger.info(
            "parse_url_selenium success: title_len=%d h1_len=%d paragraph_len=%d",
            len(title), len(h1), len(first_paragraph),
        )
        return title, h1, first_paragraph, ""
    except _SeleniumTimeoutException as e:
        logger.warning("parse_url_selenium timeout: url=%s error=%s", redact_url(url), e)
        return "", "", "", SELENIUM_TIMEOUT_MESSAGE
    except Exception as e:
        logger.warning(
            "parse_url_selenium failed: url=%s error_type=%s error=%s", redact_url(url), type(e).__name__, e
        )
        return "", "", "", SELENIUM_UPSTREAM_ERROR_MESSAGE
    finally:
        # A driver.quit() failure here must never mask the classification already decided
        # above (e.g. a real navigation TimeoutException must still surface as a timeout, not
        # get replaced by whatever quit() itself raised) — see docs.md / item 4 of the
        # corrective pass. Logged only; never re-raised or leaked to the caller. `driver` is
        # None if construction itself failed (nothing to quit in that case).
        if driver is not None:
            try:
                driver.quit()
            except Exception as quit_err:
                logger.warning(
                    "parse_url_selenium: driver.quit() failed: url=%s error=%s", redact_url(url), quit_err
                )


def parse_url_auto(
    url: str,
    timeout: float = 10.0,
    user_agent: str | None = None,
    use_selenium: bool = False,
    *,
    connect_timeout: float = 10.0,
    max_redirects: int = 5,
    max_response_bytes: int = 5 * 1024 * 1024,
    allow_no_sandbox: bool = False,
    transport: httpx.BaseTransport | None = None,
    resolver=None,
) -> tuple[str, str, str, str]:
    """
    Парсинг URL: при use_selenium=True — Selenium, иначе httpx. `connect_timeout`/
    `max_redirects`/`max_response_bytes` — конфигурация httpx-пути (см. backend.config);
    для Selenium `max_response_bytes` переиспользуется как символьный предел размера
    page_source (см. DEFAULT_MAX_PAGE_SOURCE_CHARS выше). `transport`/`resolver` — точки
    внедрения для тестов httpx-пути (см. tests/test_parser_service.py), Selenium их не
    использует.
    """
    if use_selenium and _SELENIUM_AVAILABLE:
        return parse_url_selenium(
            url,
            timeout=timeout,
            user_agent=user_agent,
            allow_no_sandbox=allow_no_sandbox,
            max_page_source_chars=max_response_bytes,
        )
    return parse_url(
        url,
        timeout=timeout,
        user_agent=user_agent,
        connect_timeout=connect_timeout,
        max_redirects=max_redirects,
        max_response_bytes=max_response_bytes,
        transport=transport,
        resolver=resolver,
    )


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
    *,
    allow_no_sandbox: bool = False,
    max_page_source_chars: int = DEFAULT_MAX_PAGE_SOURCE_CHARS,
) -> tuple[bytes | None, str, str, str]:
    """
    Открыть URL через Selenium, сделать скриншот и извлечь текст.
    Возврат: (screenshot_png_bytes, mime_type, extracted_text, error_message).
    При ошибке screenshot=None, error_message — стабильное санитизированное сообщение
    (SELENIUM_*_MESSAGE выше), никогда сырой текст исключения webdriver; полная информация
    для диагностики уходит только в серверный лог.

    Только начальный URL проверяется политикой безопасности (backend.services.url_safety);
    Selenium не даёт управлять редиректами постранично, поэтому поддерживаются только
    доверенные/публичные URL конкурентов (см. docs.md).
    """
    if not _SELENIUM_AVAILABLE:
        return None, "image/png", "", SELENIUM_NOT_INSTALLED_MESSAGE
    validate_public_http_url(url)
    logger.info("get_url_screenshot_and_text: url=%s timeout=%s", redact_url(url), timeout)
    driver = None
    try:
        driver = _new_chrome_driver(user_agent, allow_no_sandbox=allow_no_sandbox)
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        screenshot_png = driver.get_screenshot_as_png()
        html = driver.page_source
        if len(html) > max_page_source_chars:
            html = html[:max_page_source_chars]
        extracted_text = _extract_full_text(html)
        logger.info(
            "get_url_screenshot_and_text success: screenshot_len=%d text_len=%d",
            len(screenshot_png or []), len(extracted_text),
        )
        return screenshot_png, "image/png", extracted_text, ""
    except _SeleniumTimeoutException as e:
        logger.warning("get_url_screenshot_and_text timeout: url=%s error=%s", redact_url(url), e)
        return None, "image/png", "", SELENIUM_TIMEOUT_MESSAGE
    except Exception as e:
        logger.warning(
            "get_url_screenshot_and_text failed: url=%s error_type=%s error=%s",
            redact_url(url), type(e).__name__, e,
        )
        return None, "image/png", "", SELENIUM_UPSTREAM_ERROR_MESSAGE
    finally:
        # See parse_url_selenium above: a driver.quit() failure here must never mask the
        # classification already decided (timeout vs. generic Selenium failure vs. success).
        # `driver` is None if construction itself failed (nothing to quit in that case).
        if driver is not None:
            try:
                driver.quit()
            except Exception as quit_err:
                logger.warning(
                    "get_url_screenshot_and_text: driver.quit() failed: url=%s error=%s",
                    redact_url(url), quit_err,
                )
