"""ES-9 (optional): read the episode title from the title card with Tesseract."""

from __future__ import annotations

import re
import shutil

import numpy as np

from tellybox.detect import Region

LANGUAGES = "eng+nld+deu"  # the image installs these (Dockerfile)


def available() -> bool:
    """Whether the tesseract binary is installed; without it, titles are simply not read."""
    return shutil.which("tesseract") is not None


def read_title(frame: np.ndarray, region: Region | None) -> str:
    """The cleaned-up title text in ``region`` of a full-resolution gray frame, or "" (also when unavailable)."""
    if not available():
        return ""
    import cv2
    import pytesseract

    crop = region.crop(frame) if region else frame
    if crop.size == 0:
        return ""
    if crop.ndim == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Tesseract wants dark text on a light background; a title card is usually the reverse.
    if binary.mean() < 127:
        binary = 255 - binary
    try:
        if region is not None:  # the admin pointed at the title: read it as one line
            text = pytesseract.image_to_string(binary, lang=LANGUAGES, config="--psm 7")
        else:
            text = _largest_line(pytesseract.image_to_data(
                binary, lang=LANGUAGES, config="--psm 11", output_type=pytesseract.Output.DICT))
    except (pytesseract.TesseractError, OSError):
        return ""
    return _clean(text)


MIN_CONFIDENCE = 60  # Tesseract's per-word confidence, 0..100


def _largest_line(data: dict) -> str:
    """The whole frame holds the logo and scenery too; the title is usually the biggest confident text.

    Words are grouped into lines by their vertical centre, and the line with the tallest words wins.
    """
    words = [
        (data["left"][i], data["top"][i] + data["height"][i] / 2, data["height"][i], data["text"][i].strip())
        for i in range(len(data["text"]))
        if data["text"][i].strip() and float(data["conf"][i]) >= MIN_CONFIDENCE
        and any(c.isalpha() for c in data["text"][i])
    ]
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: w[1]):
        for line in lines:
            centre = sum(w[1] for w in line) / len(line)
            height = max(w[2] for w in line)
            if abs(word[1] - centre) <= height / 2 and 0.6 <= word[2] / height <= 1.6:
                line.append(word)
                break
        else:
            lines.append([word])
    if not lines:
        return ""
    best = max(lines, key=lambda line: (sorted(w[2] for w in line)[len(line) // 2], len(line)))
    return " ".join(w[3] for w in sorted(best))


def _clean(text: str) -> str:
    text = re.sub(r"[^\w\s.,:;!?'&()\-]", "", text).replace("_", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if sum(c.isalpha() for c in text) >= 3 else ""
