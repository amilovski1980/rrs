import subprocess

out = subprocess.check_output(
    ["git", "show", "627bfb6:documents/parsers.py"],
    text=True, encoding="utf-8", errors="replace",
)
# un simple probe : est-ce que le module pdf.py de cet etat contient les basiques?
pdf = subprocess.check_output(
    ["git", "show", "627bfb6:documents/pdf.py"],
    text=True, encoding="utf-8", errors="replace",
)
print("627bfb6 PDF: 4 headers basiques:", 'def _header_classique' in pdf)
print("627bfb6 PDF: QR RGB fix:", 'convert("RGB")' in pdf)
print("627bfb6 PDF: verify QR:", '_draw_verify_qr' in pdf)
