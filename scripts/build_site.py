"""Concatenate site/template.html + all site/data_*.js into site/index.html,
the file GitHub Pages serves. Run after gen_all.py."""
import glob, os

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tpl = open(os.path.join(H, "site", "template.html"), encoding="utf-8").read()
files = sorted(glob.glob(os.path.join(H, "site", "data_*.js")))
data = "\n".join(open(f, encoding="utf-8").read() for f in files)
out = tpl.replace("/*__DATA__*/", data)
dest = os.path.join(H, "site", "index.html")
open(dest, "w", encoding="utf-8").write(out)
print("built", len(out), "bytes from", [os.path.basename(f) for f in files])
