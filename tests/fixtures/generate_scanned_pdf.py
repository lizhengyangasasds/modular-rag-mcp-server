"""
Generate a scanned-style PDF for testing the PDF quality checker.

This script creates scanned.pdf — a multi-page PDF that visually contains
text but is rendered entirely as raster images, so that text extraction
(MarkItDown / pypdf) returns an empty or near-empty string. This mimics
the real-world behavior of a document scanned on a flatbed or MFP.

The PDF quality checker's `is_scanned` detector should fire on this fixture
because all sampled pages have valid_char_ratio < 10%.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter


def _render_page_image(width: int, height: int, page_num: int, total_pages: int) -> Image.Image:
    """Render a fake 'scanned' page as a high-resolution raster image.

    Visually contains Chinese + English text rendered as pixels only — no
    embedded PDF text layer. This is exactly what comes out of a real
    MFP/flatbed scanner.
    """
    img = Image.new("RGB", (width, height), color=(248, 248, 245))
    draw = ImageDraw.Draw(img)

    # Try to use a CJK-capable font; fall back to default.
    font_title = None
    font_body = None
    font_caption = None
    for candidate in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]:
        try:
            font_title = ImageFont.truetype(candidate, 56)
            font_body = ImageFont.truetype(candidate, 28)
            font_caption = ImageFont.truetype(candidate, 20)
            break
        except OSError:
            continue
    if font_title is None:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_caption = ImageFont.load_default()

    # Page header — large title
    draw.text((80, 100), f"扫描件测试文档 第 {page_num} 页", fill=(30, 30, 30), font=font_title)

    # Body paragraph
    body_lines = [
        "本页面是纯光栅化图像，文字以像素形式绘制，",
        "不包含任何可复制的文本层。",
        "",
        "This page is a rasterized image with no extractable text layer.",
        "Real scanned PDFs behave identically — MarkItDown and pypdf",
        "return an empty string for pages like this.",
        "",
        "当你用 OCR 工具（如 Tesseract、Azure Document Intelligence）",
        "处理这类 PDF 时，才能拿到真实的文字内容。",
        "",
        "Page body paragraph 2: lorem ipsum dolor sit amet, consectetur",
        "adipiscing elit, sed do eiusmod tempor incididunt ut labore et",
        "dolore magna aliqua. Ut enim ad minim veniam, quis nostrud",
        "exercitation ullamco laboris nisi ut aliquip ex ea commodo.",
    ]
    y = 220
    for line in body_lines:
        draw.text((80, y), line, fill=(20, 20, 20), font=font_body)
        y += 50

    # Simulated scan artifacts (faint noise + border)
    draw.rectangle([20, 20, width - 20, height - 20], outline=(180, 180, 180), width=2)
    # Footer page number
    draw.text(
        (width // 2 - 60, height - 70),
        f"— {page_num} / {total_pages} —",
        fill=(100, 100, 100),
        font=font_caption,
    )
    return img


def generate_scanned_pdf(output_path: Path, num_pages: int = 3) -> None:
    """Generate a scanned-style multi-page PDF.

    Each page is a full-bleed raster image, so PyMuPDF/MarkItDown will see
    no embedded text. This fixture is the canonical input for the
    `is_scanned` path of the PDF quality checker.
    """
    # Render at 150 DPI so text is legible but still pure pixels
    dpi = 150
    page_w, page_h = letter
    img_w = int(page_w * dpi / 72)
    img_h = int(page_h * dpi / 72)

    # Compose all pages as a single multi-page TIFF, then wrap in a PDF
    # using Pillow — this guarantees no text layer survives.
    images = [
        _render_page_image(img_w, img_h, i + 1, num_pages)
        for i in range(num_pages)
    ]
    images[0].save(
        str(output_path),
        save_all=True,
        append_images=images[1:],
        format="PDF",
        resolution=dpi,
    )
    print(f"PDF generated successfully: {output_path}")


if __name__ == "__main__":
    output_dir = Path(__file__).parent / "sample_documents"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "scanned.pdf"

    generate_scanned_pdf(output_file, num_pages=3)
