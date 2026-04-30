"""
slide_text_replacer
===================
Erase baked-in text from PPTX slides and overlay editable Hebrew/RTL text boxes.

Pipeline overview:
  extraction → ocr → enrichment → masking → inpainting → reconstruction

Entry point: python -m slide_text_replacer [<input.pptx> [<output.pptx>]]
"""

__version__ = "0.1.0"
