"""Small document text extraction helpers for Firefly."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx"}


def is_document_candidate(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def read_document_sample(path: Path, max_chars: int) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path, max_chars)
    if suffix == ".xlsx":
        return _read_xlsx(path, max_chars)
    if suffix == ".pptx":
        return _read_pptx(path, max_chars)
    if suffix == ".pdf":
        return _read_pdf(path, max_chars)
    return ""


def _read_docx(path: Path, max_chars: int) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    return _xml_text(xml)[:max_chars]


def _read_pptx(path: Path, max_chars: int) -> str:
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            for name in names:
                chunks.append(_xml_text(archive.read(name)))
                if sum(len(chunk) for chunk in chunks) >= max_chars:
                    break
    except (OSError, zipfile.BadZipFile):
        return ""
    return "\n".join(chunk for chunk in chunks if chunk.strip())[:max_chars]


def _read_xlsx(path: Path, max_chars: int) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _xlsx_shared_strings(archive)
            sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            rows: list[str] = []
            for name in sheet_names:
                rows.extend(_xlsx_sheet_rows(archive.read(name), shared))
                if sum(len(row) for row in rows) >= max_chars:
                    break
    except (OSError, zipfile.BadZipFile):
        return ""
    return "\n".join(rows)[:max_chars]


def _read_pdf(path: Path, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) >= max_chars:
                break
    except Exception:
        return ""
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip())[:max_chars]


def _xml_text(xml: bytes) -> str:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    parts = [node.text or "" for node in root.iter() if node.tag.endswith("}t") or node.tag == "t"]
    return _clean_text("\n".join(part for part in parts if part))


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except (KeyError, ElementTree.ParseError):
        return []
    return [_clean_text("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t") or node.tag == "t")) for item in root]


def _xlsx_sheet_rows(xml: bytes, shared: list[str]) -> list[str]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    rows: list[str] = []
    for row in root.iter():
        if not row.tag.endswith("}row") and row.tag != "row":
            continue
        values: list[str] = []
        for cell in row:
            if not cell.tag.endswith("}c") and cell.tag != "c":
                continue
            values.append(_xlsx_cell_value(cell, shared))
        line = "\t".join(value for value in values if value)
        if line:
            rows.append(line)
    return rows


def _xlsx_cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return _clean_text("".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t") or node.tag == "t"))
    value = ""
    for child in cell:
        if child.tag.endswith("}v") or child.tag == "v":
            value = child.text or ""
            break
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    return _clean_text(value)


def _clean_text(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()
