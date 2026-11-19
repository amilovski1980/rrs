# Tete Aminia + vague ronde reetablie + traits d'ecoute.
text = open("static/css/app.css", encoding="utf-8", errors="replace").read()

block = """
/* ---- Aminia : tete noire + vague ronde reetablie.
   Elle parle : les barres ondulent (vert ok).
   L utilisateur parle : traits d'ecoute qui pulsent. ---- */
.agent-core {
  background: linear-gradient(180deg, #1c1c1e 0%, #131314 56%, #0a0a0b 100%) !important;
  border: 1px solid rgba(255, 255, 255, .16) !important;
  border-radius: 18px !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .08),
    0 12px 26px -14px rgba(0, 0, 0, .85) !important;
}
.agent-core::before,
.agent-core::after {
  content: ''; position: absolute; top: 28%;
  width: 12%; height: 22%; min-width: 5px; min-height: 8px;
  border-radius: 3px; background: #f4f4f4;
  box-shadow: 0 0 8px rgba(244, 244, 244, .5);
  animation: rrsBlink 4.6s ease-in-out infinite;
}
.agent-core::before { left: 26%; }
.agent-core::after { right: 26%; }
.agent-ring { border-color: rgba(207, 207, 207, .32) !important; }
.agent-wave {
  position: static; display: flex; align-items: center; justify-content: center;
  gap: 3px; height: 16px;
}
.agent-wave::before { content: none !important; }
.agent-wave i {
  display: block; width: 3px; height: 8px; border-radius: 3px;
  background: #e8e8ea; opacity: .88; animation: none;
}
.agent-dialog.is-speaking .agent-wave i,
.agent-dialog.is-thinking .agent-wave i {
  background: #8fce9a;
  animation: agentWave 1.1s ease-in-out infinite;
}
.agent-dialog.is-speaking .agent-wave i:nth-child(2) { animation-delay: .1s; }
.agent-dialog.is-speaking .agent-wave i:nth-child(3) { animation-delay: .2s; }
.agent-dialog.is-speaking .agent-wave i:nth-child(4) { animation-delay: .3s; }
.agent-dialog.is-speaking .agent-wave i:nth-child(5) { animation-delay: .4s; }
.agent-dialog.is-speaking .agent-wave i:nth-child(6) { animation-delay: .5s; }
.agent-dialog.is-speaking .agent-wave i:nth-child(7) { animation-delay: .6s; }
.agent-dialog.is-listening .agent-wave i {
  width: 4px; height: 12px; background: #f4f4f4; opacity: .55;
  animation: rrsListen 900ms ease-in-out infinite;
}
.agent-dialog.is-listening .agent-wave i:nth-child(2) { animation-delay: .12s; }
.agent-dialog.is-listening .agent-wave i:nth-child(3) { animation-delay: .24s; }
.agent-dialog.is-listening .agent-wave i:nth-child(4) { animation-delay: .36s; }
.agent-dialog.is-listening .agent-wave i:nth-child(5) { animation-delay: .48s; }
.agent-dialog.is-listening .agent-wave i:nth-child(6) { animation-delay: .6s; }
.agent-dialog.is-listening .agent-wave i:nth-child(7) { animation-delay: .72s; }
.agent-dialog.is-listening .agent-core::before,
.agent-dialog.is-listening .agent-core::after {
  animation: rrsLook .8s ease-in-out infinite alternate;
}
.agent-wave::after { content: none !important; }
@keyframes rrsListen { 0%, 100% { opacity: .25; } 50% { opacity: .95; } }
@keyframes rrsBlink { 0%, 90%, 100% { height: 22%; } 94% { height: 6%; } }
@keyframes rrsLook { from { transform: translateX(-22%); } to { transform: translateX(22%); } }
"""
text += block + "\n"
open("static/css/app.css", "w", encoding="utf-8").write(text)
print("ok", len(block))

import re

base = open("config/templates/base.html", encoding="utf-8", errors="replace").read()
m = re.search(r"(app\.css' %\}\?v=)([\d.]+)", base)
parts = m.group(2).split(".")
parts[-1] = str(int(parts[-1]) + 1)
base = base.replace(m.group(0), m.group(1) + ".".join(parts))
open("config/templates/base.html", "w", encoding="utf-8").write(base)
m2 = re.search(r"app\.css' %\}\?v=([\d.]+)", base)
print("css ->", m2.group(1))
