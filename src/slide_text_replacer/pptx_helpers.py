"""
Module: pptx_helpers
====================
Low-level XML helpers for python-pptx that the high-level API does not expose.

PowerPoint represents text runs in DrawingML XML. python-pptx provides a
Python abstraction layer over this XML, but two properties critical for
correct Hebrew rendering require dropping down to the raw lxml element tree:

  1. Complex-script font (<a:cs>) — python-pptx's run.font API only sets
     <a:latin>. Hebrew characters are rendered using the complex-script font
     element. Without <a:cs>, Hebrew text falls back to the user's system
     default complex-script font (typically David or Arial), regardless of
     the Latin typeface setting. See notes.md §6.1.

  2. RTL paragraph attribute — Without rtl="1" on <a:pPr>, PowerPoint renders
     Hebrew text left-to-right, causing visual garbling. See notes.md §6.2.

Core functions (used by reconstruction.py):
  - set_run_font(run, font_name) -> None:
    Clears any existing <a:latin>, <a:cs>, <a:ea> elements from the run's
    rPr, then adds <a:latin typeface=font_name> and <a:cs typeface=font_name>.
    Also sets lang="he-IL" for correct bidirectional behavior.
  - set_paragraph_rtl(paragraph) -> None:
    Sets rtl="1" on the paragraph's <a:pPr> element.

Pipeline role: called by reconstruction._add_text_box() for every text run
  and paragraph. Not called from any other module.

References:
  - notes.md §6.1 (complex-script font rationale + exact implementation)
  - notes.md §6.2 (RTL paragraph attribute rationale)
  - OOXML spec: DrawingML §21.1.2.3 (rPr), §21.1.2.2 (pPr)
"""

from __future__ import annotations

from lxml import etree
from pptx.oxml.ns import qn


def set_run_font(run, font_name: str) -> None:
    """
    Set the typeface on a text run for both Latin and Hebrew (complex-script).

    python-pptx's high-level font.name property only writes <a:latin>.
    Hebrew characters are rendered using the complex-script font (<a:cs>),
    which must be set separately. Without this, Hebrew falls back to the
    system default complex-script font regardless of the intended font.

    This function:
      1. Removes any existing <a:latin>, <a:cs>, <a:ea> child elements to
         prevent duplicates.
      2. Appends <a:latin typeface=font_name> and <a:cs typeface=font_name>.
      3. Sets lang="he-IL" on the rPr element for correct bidi behavior.

    Note: <a:ea> (East Asian font) is cleared but not re-added. It is not
    needed for Hebrew and omitting it lets PowerPoint use its default East
    Asian font, which is correct behavior.

    Args:
        run:       A python-pptx Run object from paragraph.add_run().
        font_name: Typeface name to set, e.g. "Heebo" or "Frank Ruhl Libre".
                   Must be a font available as a Microsoft 365 cloud font.

    Returns:
        None. Modifies the run's underlying XML in place.
    """
    rPr = run._r.get_or_add_rPr()

    # Remove any existing font elements to avoid duplicates.
    for tag in ("a:latin", "a:cs", "a:ea"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)

    # Add Latin typeface.
    latin = etree.SubElement(rPr, qn("a:latin"))
    latin.set("typeface", font_name)

    # Add complex-script typeface (required for Hebrew — see module docstring).
    cs = etree.SubElement(rPr, qn("a:cs"))
    cs.set("typeface", font_name)

    # Mark the run as Hebrew for correct bidirectional text rendering.
    rPr.set("lang", "he-IL")


def set_paragraph_rtl(paragraph) -> None:
    """
    Mark a paragraph as right-to-left for correct Hebrew text rendering.

    PowerPoint renders Hebrew text in correct visual order only when the
    paragraph has rtl="1" on its <a:pPr> element. This is separate from
    text alignment — a right-aligned paragraph without rtl="1" will still
    render Hebrew in left-to-right logical order.

    Use this alongside paragraph.alignment = PP_ALIGN.RIGHT for all
    paragraphs containing Hebrew text.

    Args:
        paragraph: A python-pptx Paragraph object from text_frame.paragraphs
                   or text_frame.add_paragraph().

    Returns:
        None. Modifies the paragraph's underlying XML in place.
    """
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("rtl", "1")
