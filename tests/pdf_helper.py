from __future__ import annotations

from pathlib import Path


def write_text_pdf(
    path: Path,
    *,
    pages: int = 2,
    lines_by_page: list[list[tuple[float, float, float, str]]] | None = None,
    page_size: tuple[float, float] = (612, 792),
    rotation: int = 0,
    text_render_mode: int = 0,
) -> None:
    """Write selectable Helvetica text at (x, baseline from top, size, text)."""
    if lines_by_page is None:
        lines_by_page = [
            [(48, 56 + line * 14, 11, f"Evidence {line + 1}: led a synthetic operating improvement.")
             for line in range(49)]
            for _ in range(pages)
        ]
    width, height = page_size
    pages = len(lines_by_page)
    font_number = 3 + 2 * pages
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
         + f"] /Count {pages} >>").encode(),
    ]
    for index, lines in enumerate(lines_by_page):
        content_number = 4 + 2 * index
        objects.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
             f"/Rotate {rotation} /Resources << /Font << /F1 {font_number} 0 R >> >> "
             f"/Contents {content_number} 0 R >>").encode()
        )
        content = b"\n".join(
            (f"BT {text_render_mode} Tr /F1 {size} Tf 1 0 0 1 {x} {height - baseline} Tm "
             + "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
             + ") Tj ET").encode("ascii")
            for x, baseline, size, text in lines
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = bytearray(b"%PDF-1.4\n%synthetic selectable resume fixture\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                 f"startxref\n{xref}\n%%EOF\n").encode())
    path.write_bytes(data)


def write_minimal_pdf(path: Path, *, pages: int = 1) -> None:
    """Write a small, structurally valid PDF without production dependencies."""
    if pages < 1:
        raise ValueError("a PDF needs at least one page")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids ["
            + b" ".join(
                f"{number} 0 R".encode("ascii")
                for number in range(3, 3 + pages)
            )
            + f"] /Count {pages} >>".encode("ascii")
        ),
    ]
    content_number = 3 + pages
    for _ in range(pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_number} 0 R >>"
            ).encode("ascii")
        )
    objects.append(b"<< /Length 0 >>\nstream\n\nendstream")

    data = bytearray(b"%PDF-1.4\n%synthetic\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(data)
