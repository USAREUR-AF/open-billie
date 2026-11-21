"""Draw the repository's figures from the tree.

    python3 -I docs/figures/make-figures.py           # write docs/figures/*.svg
    python3 -I docs/figures/make-figures.py --check   # exit 1 if a committed figure is out of date

Each figure is written twice, `<name>-light.svg` and `<name>-dark.svg`, for a
`<picture>` element. Names, versions, ports and formats are read from the tree:
deploy/VERSION, kids/examples/oetf/billie-kid.yaml, the canonical track schema,
the translator service template and the `billie` command. The output is
deterministic. Standard library only.
"""

import json
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

THEMES = {
    "light": {
        "paper": "#ffffff", "panel": "#f6f8fa", "ink": "#1f2328", "quiet": "#59636e", "rule": "#d1d9e0",
        "line": "#818b98", "accent": "#0969da", "accent_soft": "#ddf4ff", "on_accent": "#ffffff",
        "good": "#1a7f37", "good_bg": "#dafbe1", "crit": "#cf222e", "crit_bg": "#ffebe9", "mute": "#6e7781",
        "s0": "#0969da", "s1": "#bc4c00", "s2": "#1a7f37", "s3": "#8250df",
    },
    "dark": {
        "paper": "#0d1117", "panel": "#161b22", "ink": "#e6edf3", "quiet": "#9198a1", "rule": "#3d444d",
        "line": "#7d8590", "accent": "#4493f8", "accent_soft": "#132c4c", "on_accent": "#0d1117",
        "good": "#3fb950", "good_bg": "#12261e", "crit": "#f85149", "crit_bg": "#2f1517", "mute": "#8b949e",
        "s0": "#4493f8", "s1": "#f0883e", "s2": "#3fb950", "s3": "#bc8cff",
    },
}
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"


def n(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")


def tw(s, size, mono=False, bold=False):
    """Text width estimate; the browser check in the README confirms it."""
    if mono:
        return len(s) * size * 0.61
    w = 0.0
    for c in s:
        if c in "il.,:;|!'`·1 ":
            w += 0.30
        elif c in "ft()[]/-":
            w += 0.36
        elif c in "mwMW@%":
            w += 0.86
        elif c.isupper() or c in "0123456789≤≥²→":
            w += 0.64
        else:
            w += 0.55
    return w * size * (1.06 if bold else 1.0)


def wrap(s, width, size, mono=False, bold=False):
    out, line = [], ""
    for word in s.split(" "):
        t = word if not line else line + " " + word
        if tw(t, size, mono, bold) <= width or not line:
            line = t
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


class SVG:
    def __init__(self, w, h, title, desc):
        self.w, self.h, self.title, self.desc = w, h, title, desc
        self.items = []

    def add(self, s):
        self.items.append(s)

    def rect(self, x, y, w, h, fill="panel", stroke="rule", rx=8, sw=1, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="{%s}" stroke="{%s}" stroke-width="%s"%s/>'
                 % (n(x), n(y), n(w), n(h), n(rx), fill, stroke, n(sw), d))

    def text(self, x, y, s, size=14, fill="ink", anchor="start", bold=False, mono=False, italic=False):
        self.add('<text x="%s" y="%s" font-size="%s" fill="{%s}" text-anchor="%s"%s%s%s>%s</text>'
                 % (n(x), n(y), n(size), fill, anchor, ' font-weight="600"' if bold else "",
                    ' font-family="%s"' % MONO if mono else "", ' font-style="italic"' if italic else "", escape(s)))

    def lines(self, x, y, rows, size=14, lead=1.4, **kw):
        for i, r in enumerate(rows):
            self.text(x, y + i * size * lead, r, size, **kw)
        return y + len(rows) * size * lead

    def line(self, x1, y1, x2, y2, stroke="line", sw=1.5, dash=None, arrow=False):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#arrow)"' if arrow else ""
        self.add('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="{%s}" stroke-width="%s"%s%s/>'
                 % (n(x1), n(y1), n(x2), n(y2), stroke, n(sw), d, m))

    def path(self, d, stroke="line", fill="none", sw=1.5, dash=None, arrow=False):
        dd = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#arrow)"' if arrow else ""
        f = "none" if fill == "none" else "{%s}" % fill
        self.add('<path d="%s" fill="%s" stroke="{%s}" stroke-width="%s"%s%s/>' % (d, f, stroke, n(sw), dd, m))

    def circle(self, x, y, r, fill="ink", stroke=None, sw=1.5):
        s = ' stroke="{%s}" stroke-width="%s"' % (stroke, n(sw)) if stroke else ""
        f = "none" if fill == "none" else "{%s}" % fill
        self.add('<circle cx="%s" cy="%s" r="%s" fill="%s"%s/>' % (n(x), n(y), n(r), f, s))

    def ellipse(self, x, y, rx, ry, fill="none", stroke="line", sw=1.5, dash=None, opacity=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        f = "none" if fill == "none" else "{%s}" % fill
        o = ' fill-opacity="%s"' % opacity if opacity is not None else ""
        self.add('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="%s"%s stroke="{%s}" stroke-width="%s"%s/>'
                 % (n(x), n(y), n(rx), n(ry), f, o, stroke, n(sw), d))

    def render(self, theme):
        t = THEMES[theme]
        body = "\n".join(self.items)
        for k, v in t.items():
            body = body.replace("{%s}" % k, v)
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
                'aria-labelledby="t d" font-family="%s">\n<title id="t">%s</title>\n<desc id="d">%s</desc>\n'
                '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                'orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="%s"/></marker></defs>\n'
                '<rect width="100%%" height="100%%" rx="12" fill="%s"/>\n%s\n</svg>\n'
                % (self.w, self.h, self.w, self.h, SANS.replace("'", "&apos;"), escape(self.title), escape(self.desc),
                   t["line"], t["paper"], body))


def header(f, title, sub):
    """Title and subtitle at the top left."""
    f.text(24, 38, title, 20, bold=True)
    f.text(24, 62, sub, 14, fill="quiet")




# ---------------------------------------------------------------- tree facts

def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def need(cond, what):
    if not cond:
        sys.exit("make-figures: %s not found in the tree; the figure would not match it" % what)


def kid_manifest(rel):
    """The few manifest members the figure shows, read without a YAML library."""
    text = read(rel)
    kid = re.search(r"^metadata:\n(?:  .*\n)*?  id: (\S+)", text, re.M)
    impls = re.search(r"^decoderImplementations:\n((?:  .*\n|\s*\n|  #.*\n)*)", text, re.M)
    langs = [m.group(1) for m in re.finditer(r"^  (\w+):\n    status: deployable", impls.group(1) if impls else "", re.M)]
    inputs = re.findall(r"- name: \S+\n\s+transport: (\w+)\n\s+port: (\d+)", text)
    outputs = re.findall(r"- name: \S+\n\s+format: (\S+)", text)
    comps = re.search(r"^components:\n((?:  .*\n)*)", text, re.M)
    parts = re.findall(r"^  (\w+):", comps.group(1), re.M) if comps else []
    need(kid and langs and inputs and outputs and parts, rel + " members")
    return kid.group(1), langs, inputs, outputs, parts


def facts():
    version = read("deploy/VERSION").strip()
    kid, langs, inputs, outputs, parts = kid_manifest("kids/examples/oetf/billie-kid.yaml")
    schema = json.loads(read("schemas/canonical-track-v2.schema.json"))
    record = schema["properties"]["apiVersion"]["const"]
    sock = re.search(r"BILLIE_TRANSLATOR_SOCKET=.*/([\w.]+)", read("deploy/platform/templates/billie-translator.service.j2"))
    need(sock, "translator socket")
    cli = read("deploy/bin/billie")
    verbs = ["scan", "validate", "build", "install", "configure", "activate"]
    for v in verbs:
        need(re.search(r"\b%s\b" % v, cli.split("kid)", 1)[1].split(";;\n  mapper", 1)[0]), "billie kid " + v)
    readme = read("README.md")
    for phrase in ("linux/amd64", "linux/arm64", "Ubuntu Server 24.04", "mTLS", "local Zenoh"):
        need(phrase in readme, "README phrase " + phrase)
    return dict(version=version, kid=kid, langs=langs, inputs=inputs, outputs=outputs, parts=parts,
                record=record, sock=sock.group(1), verbs=verbs)


FORMAT_LABEL = {"cot": "CoT", "asterix-cat062": "ASTERIX CAT062", "sapient": "SAPIENT"}
LANG_LABEL = {"python": "Python", "rust": "Rust", "typescript": "TypeScript"}


# ---------------------------------------------------------------- figure

def fig_node():
    F = facts()
    W, Hh = 880, 600
    fmts = [FORMAT_LABEL.get(o, o) for o in F["outputs"]]
    langs = [LANG_LABEL.get(l, l) for l in F["langs"]]
    ports = sorted({p for _, p in F["inputs"]})
    transports = "/".join(t.upper() for t in sorted({t for t, _ in F["inputs"]}, reverse=True))
    title = "A kid package decodes one sensor; the Open Billie platform takes it to the fabric"
    desc = ("Kid packages are scanned, validated and built for linux/amd64 or linux/arm64 on a workstation, then "
            "installed, configured and activated on a node running Ubuntu Server 24.04. On the node, the %s example "
            "kid listens on %s port %s, decodes with a %s decoder and applies the user mapping and lookups, then "
            "hands a %s record over the local Unix socket %s to the platform %s. The platform's Rust translator "
            "and encoder write %s, publish to the local Zenoh island, and an mTLS fabric client and prefix bridge "
            "carry the data to the remote fabric. The kid holds no fabric credentials."
            % (F["kid"], transports, "/".join(ports), " or ".join(langs), F["record"], F["sock"], F["version"],
               ", ".join(fmts), ))
    f = SVG(W, Hh, title, desc)
    header(f, title, "The kid decodes and maps. The platform translates, encodes and bridges. Shown: the synthetic %s example kid." % F["kid"].upper())

    # build-and-deploy strip
    y0 = 92
    f.text(24, y0 + 4, "Build and deploy a kid", 14, bold=True)
    f.text(24 + tw("Build and deploy a kid", 14, bold=True) + 10, y0 + 4,
           "builds for linux/amd64 or linux/arm64; one listener active per kid", 14, fill="quiet")
    cy = y0 + 22
    chip_h = 30
    x = 24
    labels = ["billie kid " + F["verbs"][0]] + F["verbs"][1:]
    gap = 26
    widths = [tw(s, 14, mono=True) + 24 for s in labels]
    spare = (W - 48 - sum(widths) - gap * (len(labels) - 1)) / len(labels)
    for i, s in enumerate(labels):
        w = widths[i] + spare
        f.rect(x, cy, w, chip_h, fill="panel", stroke="rule", rx=6)
        f.text(x + w / 2, cy + 20, s, 14, anchor="middle", mono=True)
        if i < len(labels) - 1:
            f.line(x + w + 3, cy + chip_h / 2, x + w + gap - 4, cy + chip_h / 2, arrow=True)
        if i == 2:
            split = x + w + gap / 2
        x += w + gap
    f.text(24, cy + chip_h + 20, "on the workstation", 13, fill="quiet")
    f.text(split + 8, cy + chip_h + 20, "on the node", 13, fill="quiet")
    f.line(split, cy - 6, split, cy + chip_h + 24, stroke="rule", dash="3 3")

    # the node: lay out the inside first, then size the node box to it
    ny = 196
    bh = 62
    vgap = 22
    nx = 140
    kx, kw = nx + 16, 224
    px = 516
    pw = W - 40 - px
    ky = ny + 44
    inner = ky + 60
    qx, qw = px + 14, pw - 28
    # format chips flow onto as many rows as the box width needs
    chips, cx, cyy = [], 0, 0
    for s in fmts:
        w = tw(s, 13) + 18
        if cx and cx + w > qw - 28:
            cx, cyy = 0, cyy + 38
        chips.append((cx, cyy, w, s))
        cx += w + 8
    t_h = 42 + cyy + 30 + 16
    k_end = inner + 3 * bh + 2 * vgap
    p_end = inner + t_h + 2 * (vgap + bh)
    kh = k_end + 16 - ky
    ph = p_end + 16 - ky
    nh = ky + max(kh, ph) + 16 - ny
    fab_h = 40
    Hh = ny + nh + 30 + fab_h + 24
    f.h = Hh
    f.rect(nx, ny, W - 24 - nx, nh, fill="paper", stroke="line", rx=12, sw=1.5)
    f.text(nx + 16, ny + 26, "Node", 15, bold=True)
    f.text(nx + 16 + tw("Node", 15, bold=True) + 10, ny + 26, "Ubuntu Server 24.04 · amd64 or arm64", 14, fill="quiet")

    # sensor, outside the node, level with the listener
    sx, sw_ = 24, nx - 24 - 28
    f.rect(sx, inner, sw_, bh + 20, fill="panel", stroke="rule")
    f.text(sx + sw_ / 2, inner + 26, "Sensor", 15, anchor="middle", bold=True)
    f.text(sx + sw_ / 2, inner + 47, transports, 13, anchor="middle", fill="quiet")
    f.text(sx + sw_ / 2, inner + 65, "port " + "/".join(ports), 13, anchor="middle", fill="quiet")

    # kid zone
    f.rect(kx, ky, kw, kh, fill="accent_soft", stroke="accent", rx=10, sw=1.5, dash="6 4")
    f.text(kx + 14, ky + 24, "Kid package · %s" % F["kid"], 15, bold=True)
    f.text(kx + 14, ky + 44, "one per sensor, from its owner", 13, fill="quiet")
    bx, bw = kx + 14, kw - 28
    boxes_k = [("Listener and decoder", " · ".join(langs)),
               ("User mapping", "mappings and lookups"),
               ("Conformance vectors", "synthetic data")]
    ys = []
    yy = inner
    for a, b in boxes_k:
        f.rect(bx, yy, bw, bh, fill="paper", stroke="accent")
        f.text(bx + 14, yy + 26, a, 15, bold=True)
        f.text(bx + 14, yy + 47, b, 13, fill="quiet")
        ys.append(yy)
        yy += bh + vgap
    f.line(bx + bw / 2, ys[0] + bh + 2, bx + bw / 2, ys[1] - 3, arrow=True)
    f.line(sx + sw_ + 2, inner + bh / 2, bx - 3, inner + bh / 2, arrow=True)

    # platform zone
    f.rect(px, ky, pw, ph, fill="panel", stroke="good", rx=10, sw=1.5)
    f.text(px + 14, ky + 24, "Open Billie platform %s" % F["version"], 15, bold=True)
    f.text(px + 14, ky + 44, "one per node; holds the fabric credentials", 13, fill="quiet")
    ty = inner
    f.rect(qx, ty, qw, t_h, fill="paper", stroke="good")
    f.text(qx + 14, ty + 26, "Rust translator and encoder", 15, bold=True)
    for cx, cyy, w, s in chips:
        f.rect(qx + 14 + cx, ty + 42 + cyy, w, 30, fill="good_bg", stroke="good", rx=6)
        f.text(qx + 14 + cx + w / 2, ty + 62 + cyy, s, 13, anchor="middle")
    zy = ty + t_h + vgap
    f.rect(qx, zy, qw, bh, fill="paper", stroke="good")
    f.text(qx + 14, zy + 26, "Local Zenoh island", 15, bold=True)
    f.text(qx + 14, zy + 47, "one local route per kid output", 13, fill="quiet")
    by = zy + bh + vgap
    f.rect(qx, by, qw, bh, fill="paper", stroke="good")
    f.text(qx + 14, by + 26, "mTLS fabric client and bridge", 15, bold=True)
    f.text(qx + 14, by + 47, "prefix bridge to the remote fabric", 13, fill="quiet")
    f.line(qx + qw / 2, ty + t_h + 2, qx + qw / 2, zy - 3, arrow=True)
    f.line(qx + qw / 2, zy + bh + 2, qx + qw / 2, by - 3, arrow=True)

    # out of the node to the fabric
    fy = ny + nh + 30
    fx = qx + qw / 2
    f.line(fx, by + bh + 2, fx, fy - 3, arrow=True)
    fw = tw("Remote data fabric", 15, bold=True) + 40
    f.rect(fx - fw / 2, fy, fw, fab_h, fill="accent_soft", stroke="accent", rx=20)
    f.text(fx, fy + 26, "Remote data fabric", 15, anchor="middle", bold=True)

    # handoff: mapper -> translator, labels in the gap under the line
    hy = ys[1] + bh / 2
    vx = qx - 22
    f.path("M%s,%s H%s V%s H%s" % (n(bx + bw + 2), n(hy), n(vx), n(ty + 26), n(qx - 3)),
           stroke="accent", sw=2, arrow=True)
    gx = (kx + kw + vx) / 2
    f.text(gx, hy + 24, F["record"].split("/")[1] + " record", 13, anchor="middle", bold=True)
    f.text(gx, hy + 42, "over the local", 13, anchor="middle", fill="quiet")
    f.text(gx, hy + 60, "Unix socket", 13, anchor="middle", fill="quiet")
    f.text(gx, hy + 78, F["sock"], 13, anchor="middle", mono=True, fill="quiet")
    return f


FIGURES = [("open-billie-node", fig_node)]


def main(argv):
    check = "--check" in argv
    stale = []
    for name, fn in FIGURES:
        fig = fn()
        for theme in THEMES:
            p = os.path.join(HERE, "%s-%s.svg" % (name, theme))
            out = fig.render(theme)
            if check:
                if not os.path.isfile(p) or open(p, encoding="utf-8").read() != out:
                    stale.append(os.path.relpath(p, ROOT))
            else:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(out)
                print(os.path.relpath(p, ROOT))
    if stale:
        print("out of date: " + ", ".join(stale) + "; run python3 -I docs/figures/make-figures.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
