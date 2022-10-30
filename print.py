import os
import subprocess
import tempfile
import logging
import pdfkit
from bs4 import BeautifulSoup
from pyvirtualdisplay import Display
from constants import date

PDFKIT_PRESENT = ' ' in subprocess.check_output("whereis wkhtmltopdf", shell=True).decode()
if not PDFKIT_PRESENT:
    if os.name == "nt":
        CHROME_PATH = "C:\Program Files\Google\Chrome\Application/chrome"
        # TODO: registry lookup
    elif os.name == "posix":
        CHROME_PATH = subprocess.check_output("whereis google-chrome", shell=True).decode().split(" ")[1]


def print_to_pdf(arg, pdf_path=None):
    remove = True
    if type(arg) == str:
        htm_path = arg
        pdf_path = pdf_path or os.path.abspath(htm_path.replace('_processed.htm', '.pdf'))
        htm_path = os.path.abspath(htm_path)
    elif type(arg) == BeautifulSoup:
        with tempfile.NamedTemporaryFile(delete=False, mode="wb", suffix=".htm", dir=f"./{date}") as f:
            f.write(arg.prettify(encoding='UTF-8'))
        htm_path = os.path.abspath(f.name)
        pdf_path = os.path.abspath(pdf_path or (arg.h1.string + ".pdf"))
    if PDFKIT_PRESENT:
        with Display():
            pdfkit.from_file(htm_path, pdf_path, options={
                'encoding': 'utf-8',
                'orientation': 'portrait',
                'page-size': 'A4',
                'margin-top': '0mm', 'margin-bottom': '0mm', 'margin-left': '0mm', 'margin-right': '0mm'
            })
    else:
        cmd = f'"{CHROME_PATH}" --headless --disable-gpu --no-sandbox --print-to-pdf="{pdf_path}" --no-margins "{htm_path}"'
        try:
            subprocess.check_output(cmd, shell=True)
            if remove:
                os.remove(htm_path)
        except:
            pdf_path = htm_path
    return pdf_path
