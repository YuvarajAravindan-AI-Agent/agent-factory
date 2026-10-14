import hashlib, html, json, os, subprocess, sys
import numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
from playwright.sync_api import sync_playwright
import content as C

HERE = os.path.dirname(os.path.abspath(__file__))
COL = {"agent": "#38bdf8", "gate": "#2dd4bf", "fixer": "#c084fc", "human": "#fbbf24",
       "fail": "#fb7185", "ok": "#4ade80", "neutral": "#94a3b8"}
VOICE, SPEED = "af_heart", 0.97
esc = html.escape

CSS = """
*{box-sizing:border-box;margin:0}
body{width:1920px;height:1080px;overflow:hidden;font-family:Inter,sans-serif;color:#eef2ff;
background:radial-gradient(1200px 700px at 15% 0%,#2a1b5e 0%,transparent 60%),radial-gradient(1000px 700px at 100% 100%,#0b3b4f 0%,transparent 60%),#0a0f24}
.top{position:absolute;left:80px;right:80px;top:52px;display:flex;align-items:center;gap:24px}
.tag{font-size:24px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#0a0f24;background:#a5b4fc;padding:8px 18px;border-radius:999px}
h1{font-size:58px;font-weight:800;line-height:1.1;letter-spacing:-.01em}
.body{position:absolute;left:80px;right:80px;top:170px;bottom:170px}
.cap{position:absolute;left:0;right:0;bottom:8px;height:150px;background:rgba(5,8,22,.78);display:flex;align-items:center;justify-content:center;padding:0 140px;
font-size:35px;line-height:1.35;text-align:center;font-weight:500;color:#f4f6ff}
.prog{position:absolute;left:0;bottom:0;height:8px;background:linear-gradient(90deg,#38bdf8,#c084fc,#fbbf24)}
.grid{display:grid;gap:26px;height:100%;align-content:start}
.card{background:linear-gradient(160deg,rgba(255,255,255,.11),rgba(255,255,255,.04));border:2px solid color-mix(in srgb,var(--c) 55%,transparent);
border-radius:22px;padding:26px 28px;display:flex;flex-direction:column;gap:12px;box-shadow:0 10px 40px rgba(0,0,0,.35)}
.chip{align-self:flex-start;font-size:21px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#0a0f24;background:var(--c);padding:5px 14px;border-radius:999px}
.card h3{font-size:36px;font-weight:700;line-height:1.15}
.card p{font-size:27px;line-height:1.38;color:#cfd6ee}
.dense .card h3{font-size:32px}.dense .card p{font-size:24px}
.title{display:flex;flex-direction:column;justify-content:center;height:100%;gap:36px}
.title .big{font-size:128px;font-weight:800;line-height:1.02;letter-spacing:-.02em;background:linear-gradient(90deg,#38bdf8,#c084fc 55%,#fbbf24);-webkit-background-clip:text;color:transparent}
.title .sub{font-size:44px;color:#dbe2ff;max-width:1500px;line-height:1.25}
.chips{display:flex;gap:18px;flex-wrap:wrap}.chips .chip{font-size:28px;padding:10px 24px}
.flow{display:flex;flex-direction:column;gap:56px;justify-content:center;height:100%}
.row{display:flex;align-items:center;gap:0}
.node{flex:1;min-width:0;border:2px solid var(--c);background:color-mix(in srgb,var(--c) 20%,#0a0f24);border-radius:18px;padding:20px 12px;text-align:center;transition:none}
.node b{display:block;font-size:30px;line-height:1.15}.node span{display:block;font-size:20px;color:#cfd6ee;margin-top:6px}
.node.on{box-shadow:0 0 0 4px color-mix(in srgb,var(--c) 45%,transparent),0 0 44px var(--c);transform:scale(1.04);background:color-mix(in srgb,var(--c) 38%,#0a0f24)}
.node.off{opacity:.3}
.arr{width:34px;text-align:center;font-size:30px;color:#8b95bb;flex:none}
.cont{text-align:right;color:#8b95bb;font-size:24px;margin-top:-30px}
.legend{display:flex;gap:26px;justify-content:center;font-size:24px;color:#cfd6ee}.legend i{display:inline-block;width:20px;height:20px;border-radius:6px;margin-right:10px;vertical-align:-3px}
.term{background:#070b1a;border:2px solid #2b3560;border-radius:20px;padding:34px 40px;font-family:'DejaVu Sans Mono',monospace;font-size:31px;line-height:1.75;height:100%;box-shadow:0 10px 40px rgba(0,0,0,.4)}
.term .c{color:#7d88b5}.term .p{color:#4ade80}.term .l{white-space:pre-wrap;word-break:break-all}
"""


def card_html(c, shown):
    st = "" if shown else "opacity:0;"
    return (f'<div class="card" style="--c:{COL[c["kind"]]};{st}"><span class="chip">{esc(c["chip"])}</span>'
            f'<h3>{esc(c["title"])}</h3><p>{esc(c["text"])}</p></div>')


def body(scene, seg):
    k = scene["kind"]
    if k == "title":
        chips = "".join(f'<span class="chip" style="--c:{COL[x]}">{esc(t)}</span>' for t, x in scene["chips"])
        return (f'<div class="title"><div class="big">{esc(scene["title"])}</div>'
                f'<div class="sub">{esc(scene["sub"])}</div><div class="chips">{chips}</div></div>')
    if k == "cards":
        n = scene["cols"]; cs = scene["cards"]; show = seg.get("show", len(cs))
        dense = "dense" if n >= 4 or len(cs) >= 6 else ""
        return (f'<div class="grid {dense}" style="grid-template-columns:repeat({n},1fr)">'
                + "".join(card_html(c, i < show) for i, c in enumerate(cs)) + "</div>")
    if k == "flow":
        act = set(seg.get("active", []))
        def node(i):
            t, s, kd = C.FLOW_NODES[i]
            cls = "on" if i in act else ("off" if act else "")
            return f'<div class="node {cls}" style="--c:{COL[kd]}"><b>{esc(t)}</b><span>{esc(s)}</span></div>'
        def row(idx):
            return '<div class="row">' + '<div class="arr">›</div>'.join(node(i) for i in idx) + "</div>"
        leg = "".join(f'<span><i style="background:{COL[x]}"></i>{t}</span>' for t, x in
                      [("AI agent", "agent"), ("AWS service or check", "gate"), ("Human", "human")])
        fx = '<div class="legend"><span><i style="background:#c084fc"></i>Fixer loops back to the Tester when a step fails</span></div>'
        return (f'<div class="flow">{row(range(0, 6))}<div class="cont">continues on the next row ↓</div>{row(range(6, 12))}'
                f'<div class="legend">{leg}</div>{fx}</div>')
    if k == "terminal":
        show = seg.get("show", len(scene["lines"]))
        out = []
        for i, (t, x) in enumerate(scene["lines"]):
            st = "" if i < show else "opacity:0"
            out.append(f'<div class="l" style="{st}">' + (f'<span class="c">{esc(x)}</span>' if t == "c"
                       else f'<span class="p">$ </span>{esc(x)}') + "</div>")
        return f'<div class="term">{"".join(out)}</div>'
    raise ValueError(k)


def page(scene, seg, i, n, frac):
    return (f"<style>{CSS}</style><div class='top'><span class='tag'>{esc(scene['tag'])}</span>"
            + ("" if scene["kind"] == "title" else f"<h1>{esc(scene['title'])}</h1>")
            + f"</div><div class='body'>{body(scene, seg)}</div><div class='cap'>{esc(seg['say'])}</div>"
            f"<div class='prog' style='width:{frac*100:.2f}%'></div>")


def make(scenes, name, voice_cache, crf, scale, abr, mono):
    out = os.path.join(HERE, name); os.makedirs(out, exist_ok=True)
    kok = Kokoro(os.path.join(HERE, "kokoro.onnx"), os.path.join(HERE, "voices.bin"))
    segs = [(sc, sg, si) for si, sc in enumerate(scenes) for sg in sc["segs"]]
    total = len(segs)
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                               args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 1920, "height": 1080})
        lines, wavs, tdur = [], [], 0.0
        for j, (sc, sg, si) in enumerate(segs):
            key = hashlib.md5((VOICE + str(SPEED) + sg["say"]).encode()).hexdigest()
            wp = os.path.join(voice_cache, key + ".wav")
            if not os.path.exists(wp):
                a, sr = kok.create(sg["say"], voice=VOICE, speed=SPEED, lang="en-us")
                sf.write(wp, a, sr)
            a, sr = sf.read(wp)
            last_in_scene = (j + 1 == total) or segs[j + 1][2] != si
            pad = np.zeros(int(sr * (0.9 if last_in_scene else 0.45)))
            a = np.concatenate([a, pad]); wavs.append((a, sr))
            dur = len(a) / sr; tdur += dur
            lines.append((j, dur))
        # second pass: render with correct progress now that the total is known
        acc = 0.0; frames = []
        for j, (sc, sg, si) in enumerate(segs):
            dur = lines[j][1]; acc += dur
            pg.set_content(page(sc, sg, si, len(scenes), acc / tdur))
            fp = os.path.join(out, f"f{j:03d}.png"); pg.screenshot(path=fp); frames.append((fp, dur))
        br.close()
    sr = wavs[0][1]
    sf.write(os.path.join(out, "audio.wav"), np.concatenate([w for w, _ in wavs]), sr)
    with open(os.path.join(out, "frames.txt"), "w") as f:
        for fp, d in frames: f.write(f"file '{fp}'\nduration {d:.3f}\n")
        f.write(f"file '{frames[-1][0]}'\n")
    mp4 = os.path.join(HERE, name + ".mp4")
    vf = f"scale={scale},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(out, "frames.txt"),
                    "-i", os.path.join(out, "audio.wav"), "-vf", vf, "-r", "30", "-c:v", "libx264", "-preset", "slow",
                    "-tune", "stillimage", "-crf", str(crf), "-c:a", "aac", "-b:a", abr] + (["-ac", "1"] if mono else []) +
                   ["-movflags", "+faststart", "-shortest", mp4], check=True)
    with open(os.path.join(HERE, name + "-script.md"), "w") as f:
        f.write(f"# {name}: narration script\n\n")
        cur = None
        for sc, sg, si in segs:
            if si != cur:
                cur = si; f.write(f"\n## {si+1}. {sc['title']}\n\n")
            f.write(f"- {sg['say']}\n")
    return mp4, tdur


if __name__ == "__main__":
    which = sys.argv[1]
    vc = os.path.join(HERE, "voice"); os.makedirs(vc, exist_ok=True)
    if which == "long":
        print(make(C.DETAILED, "agent-factory-walkthrough", vc, 27, "1920:1080", "128k", False))
    else:
        print(make(C.SHORT, "agent-factory-linkedin", vc, int(sys.argv[2]) if len(sys.argv) > 2 else 30, "1280:720", "64k", True))
