"""Concatenate site/template.html + all site/data_*.js into site/index.html,
the file GitHub Pages serves. Also copies data/discovery_queue.json into
site/ so site/review.html (same directory, no CORS needed) can fetch it
fresh on every deploy. Run after gen_all.py."""
import glob, os, shutil

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tpl = open(os.path.join(H, "site", "template.html"), encoding="utf-8").read()
files = sorted(glob.glob(os.path.join(H, "site", "data_*.js")))
data = "\n".join(open(f, encoding="utf-8").read() for f in files)
out = tpl.replace("/*__DATA__*/", data)
dest = os.path.join(H, "site", "index.html")
open(dest, "w", encoding="utf-8").write(out)
print("built", len(out), "bytes from", [os.path.basename(f) for f in files])

queue_src = os.path.join(H, "data", "discovery_queue.json")
queue_dest = os.path.join(H, "site", "discovery_queue.json")
if os.path.exists(queue_src):
    shutil.copyfile(queue_src, queue_dest)
    print("copied discovery_queue.json ->", queue_dest)
