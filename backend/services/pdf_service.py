"""Извлечение текста из PDF."""
import logging
from io import BytesIO

from pypdf import PdfReader

logger = logging.getLogger("backend.services.pdf")


def extract_text_from_pdf(content: bytes) -> str:
    """
    Извлекает текст из PDF. При ошибке возвращает пустую строку.
    """
    if not content or len(content) < 100:
        return ""
    try:
        reader = PdfReader(BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                text = page.extract_text()
                if text and text.strip():
                    parts.append(text.strip())
            except Exception as e:
                logger.debug("pdf page extract error: %s", e)
        result = "\n\n".join(parts)
        logger.info("pdf extracted len=%d pages=%d", len(result), len(reader.pages))
        return result
    except Exception as e:
        logger.warning("pdf extract failed: %s", e)
        return ""
