import os
import subprocess
import aspose.slides as slides
from fastapi import HTTPException


def convert_ppt_to_pdf(file_path):
    """Convert PPT/PPTX to PDF using LibreOffice"""
    output_path = file_path.rsplit(".", 1)[0] + ".pdf"

    try:
        # Make sure LibreOffice is installed: sudo apt-get install libreoffice-common
        cmd = f'libreoffice --headless --convert-to pdf --outdir "{os.path.dirname(file_path)}" "{file_path}"'
        process = subprocess.run(
            cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        if os.path.exists(output_path):
            return output_path
        else:
            raise Exception(f"PDF file not created: {output_path}")
    except Exception as e:
        print(f"Conversion error: {str(e)}")
        raise
