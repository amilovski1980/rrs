# Fabrique un petit PDF texte (lecture via pdfminer, sans vision) pour tester
# le scan streamé de bout en bout.
import base64
import zlib


def pdf_text(filename, lines):
    content_parts = ["BT /F1 12 Tf 40 780 Td 16 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_parts.append(f"({safe}) Tj T*")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("latin-1", "replace")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                   b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    open(filename, "wb").write(out)
    print("PDF ecrit:", filename, len(out), "octets")


pdf_text(
    "static/pwa/scan-test-ticket.pdf",
    [
        "CAFE MARTIN",
        "12 rue des Lilas Paris 11",
        "CAFE 2,50",
        "CROISSANT 1,80",
        "MENU OUVRIER 9,50",
        "TOTAL HT 12,50",
        "TVA 20% 2,08",
        "TOTAL TTC 14,58",
        "CB 14/11/2026",
    ],
)
