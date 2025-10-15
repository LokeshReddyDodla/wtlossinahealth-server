import io
import mimetypes
import pdfplumber
import pandas as pd
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes
from docx import Document


class FileContentExtractorService:
    def __init__(self):
        self.ocr_lang = "eng"

    def extract(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> str:
        mime_type = content_type or mimetypes.guess_type(filename)[0]

        if mime_type == "application/pdf":
            return self._extract_pdf(file_bytes)
        elif mime_type in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]:
            return self._extract_docx(file_bytes)
        elif mime_type in [
            "text/csv",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]:
            return self._extract_csv(file_bytes)
        elif mime_type and mime_type.startswith("image/"):
            return self._extract_image(file_bytes)
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")

    def _extract_pdf(self, file_bytes: bytes) -> str:
        text = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)

        if not text:  # scanned PDF → OCR
            images = convert_from_bytes(file_bytes)
            for img in images:
                text.append(
                    pytesseract.image_to_string(img, lang=self.ocr_lang)
                )

        return "\n".join(text)

    def _extract_docx(self, file_bytes: bytes) -> str:
        doc = Document(io.BytesIO(file_bytes))
        text = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(text)

    def _extract_csv(self, file_bytes: bytes) -> str:
        df = pd.read_csv(io.BytesIO(file_bytes))
        return df.to_csv(index=False)

    def _extract_image(self, file_bytes: bytes) -> str:
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image, lang=self.ocr_lang)
