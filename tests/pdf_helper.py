from __future__ import annotations

from pathlib import Path


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
