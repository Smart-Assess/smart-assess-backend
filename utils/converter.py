import os
import aspose.slides as slides
from fastapi import HTTPException

def convert_ppt_to_pdf(ppt_path: str) -> str:
    """Converts a PPT file to PDF and returns the new PDF file path."""
    pdf_path = ppt_path.rsplit(".", 1)[0] + ".pdf"

    try:
        with slides.Presentation(ppt_path) as presentation:
            presentation.save(pdf_path, slides.export.SaveFormat.PDF)
        return pdf_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error converting PPT to PDF: {e}")

