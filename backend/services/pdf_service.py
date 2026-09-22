"""Извлечение текста из PDF."""
import logging
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from backend.errors import InvalidInputError, PayloadTooLargeError

logger = logging.getLogger("backend.services.pdf")


def extract_text_from_pdf(
    content: bytes,
    *,
    max_pages: int = 50,
    max_extracted_chars: int = 50_000,
) -> str:
    """
    Извлекает текст из PDF (не более max_pages страниц, не более max_extracted_chars символов).
    Raises PayloadTooLargeError if the document has more than max_pages pages.
    Raises InvalidInputError if the content cannot be parsed as a PDF at all.
    """
    if not content or len(content) < 100:
        return ""
    try:
        reader = PdfReader(BytesIO(content))
        num_pages = len(reader.pages)
    except (PdfReadError, ValueError, OSError) as e:
        logger.warning("pdf parse failed: %s", e)
        raise InvalidInputError("Не удалось разобрать PDF-файл. Файл повреждён или не является PDF.") from e

    if num_pages > max_pages:
        raise PayloadTooLargeError(f"PDF содержит слишком много страниц ({num_pages} > {max_pages}).")

    parts = []
    total_len = 0
    for page in reader.pages:
        try:
            text = page.extract_text()
        except Exception as e:
            logger.debug("pdf page extract error: %s", e)
            continue
        if text and text.strip():
            text = text.strip()
            parts.append(text)
            total_len += len(text)
            if total_len >= max_extracted_chars:
                break
    result = "\n\n".join(parts)
    if len(result) > max_extracted_chars:
        result = result[:max_extracted_chars]
    logger.info("pdf extracted len=%d pages=%d", len(result), num_pages)
    return result
