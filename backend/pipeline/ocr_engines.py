"""Pluggable OCR for scanned recorder documents.

Every engine returns positioned lines (page, x, y, height, text; x/y the lower-left corner
as a fraction of the page, y growing upwards), and `text_lines` rebuilds reading lines from
them: pieces at the same height are joined left to right with " | ", so a two-column form
("Purported Street Address: | 12918 N 72ND AVE ...") keeps each label beside its value.

Engines:
- "macos": Apple Vision (pipeline/ocr_pdf_macos_boxes.swift); macOS only, the most accurate here.
- "tesseract": the tesseract CLI on pages rendered with pypdfium2 (brew install tesseract).
- "auto": tesseract when installed, otherwise macos.
Another engine (AWS Textract, an LLM vision model) is a class with the same `boxes(pdf)`
method added to ENGINES.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

Box = tuple[int, float, float, float, str]


class OcrEngine(Protocol):
    name: str

    def boxes(self, pdf: Path) -> list[Box]: ...


class MacVisionOcr:
    """pixels: the longer page side when rendering (3200 by default; 5600 reads text under the
    recorder's "Unofficial Document" watermark better); correct: Vision's language correction."""
    name = "macos"
    script = Path(__file__).with_name("ocr_pdf_macos_boxes.swift")
    compiled = Path(__file__).resolve().parents[2] / ".local" / "bin" / "ocr_pdf_macos_boxes"

    def binary(self) -> Path:
        """The script compiled once (swiftc), so each document skips the compile."""
        if not self.compiled.exists() or self.compiled.stat().st_mtime < self.script.stat().st_mtime:
            self.compiled.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["swiftc", "-O", str(self.script), "-o", str(self.compiled)], check=True,
                           capture_output=True, timeout=600)
        return self.compiled

    def __init__(self, pixels: int = 3200, correct: bool = False):
        self.pixels, self.correct = pixels, correct

    def boxes(self, pdf: Path) -> list[Box]:
        command = [str(self.binary()), str(pdf), str(self.pixels)] + (["correct"] if self.correct else [])
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
        if result.returncode:
            raise RuntimeError(f"OCR failed for {pdf.name}: {result.stderr.strip()[:300]}")
        found = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 5)
            if len(parts) == 6:
                found.append((int(parts[0]), float(parts[1]), float(parts[2]), float(parts[4]), parts[5]))
        return found


class TesseractOcr:
    name = "tesseract"
    scale = 300 / 72  # 300 dpi

    def boxes(self, pdf: Path) -> list[Box]:
        import pypdfium2

        found = []
        document = pypdfium2.PdfDocument(str(pdf))
        with tempfile.TemporaryDirectory() as folder:
            for index in range(len(document)):
                image = document[index].render(scale=self.scale).to_pil()
                png = Path(folder) / f"{index}.png"
                image.save(png)
                tsv = subprocess.run(["tesseract", str(png), "stdout", "tsv"], capture_output=True, text=True,
                                     timeout=300, check=True).stdout
                found += self.lines(tsv, index + 1, image.width, image.height)
        return found

    @staticmethod
    def lines(tsv: str, page: int, width: int, height: int) -> list[Box]:
        """Tesseract's words grouped into its own lines (block, paragraph, line)."""
        grouped: dict[tuple, list] = {}
        for row in tsv.splitlines()[1:]:
            cells = row.split("\t")
            if len(cells) < 12 or not cells[11].strip():
                continue
            left, top, w, h = (int(value) for value in cells[6:10])
            grouped.setdefault(tuple(cells[2:5]), []).append((left, top, w, h, cells[11]))
        found = []
        for words in grouped.values():
            left = min(word[0] for word in words)
            bottom = max(word[1] + word[3] for word in words)
            tall = max(word[3] for word in words)
            found.append((page, left / width, 1 - bottom / height, tall / height, " ".join(word[4] for word in words)))
        return found


ENGINES = {"macos": MacVisionOcr, "tesseract": TesseractOcr}


def engine(name: str = "auto") -> OcrEngine:
    if name == "auto":
        name = "tesseract" if shutil.which("tesseract") else "macos"
    return ENGINES[name]()


def text_lines(boxes: list[Box]) -> list[str]:
    ordered = sorted(boxes, key=lambda box: (box[0], -box[2], box[1]))
    lines: list[list[Box]] = []
    for box in ordered:
        last = lines[-1][0] if lines else None
        if last and last[0] == box[0] and abs(last[2] - box[2]) < max(last[3], box[3]) * 0.5:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [" | ".join(piece[4].strip() for piece in sorted(line, key=lambda piece: piece[1])) for line in lines]
