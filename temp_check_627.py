import subprocess

out = subprocess.check_output(
    ["git", "show", "627bfb6:documents/urls.py"],
    text=True, encoding="utf-8", errors="replace",
)
needle = "v/<uuid:pk>"
print("627bfb6 (/prod actuel) contient la route /v/ :", needle in out)

log = subprocess.check_output(
    ["git", "log", "627bfb6", "--oneline", "-2"],
    text=True, encoding="utf-8", errors="replace",
)
print(log)
