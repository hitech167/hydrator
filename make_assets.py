"""Turn the green-screen character pictures into small transparent frames for the app.

Input (in this folder):  stand.png, drink.png, remind.png   (character on a green background)
Output:                  assets/*.png
Run:  python make_assets.py
"""
import json
import os

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "characters")    # characters/<name>/stand.png, drink.png, walk.png [, character.json]
OUT = os.path.join(HERE, "assets")         # assets/<name>/...   (built frames, used by the app)
STAND_H = 300       # on-screen height (px) of the standing character
REMIND_H = 340      # on-screen height of the close-up reminder pose
FRAMES_IN_SHEET = 6   # frames in walk.png
DESPILL = False       # set per character from character.json ("despill": true)
PAD = 24            # transparent margin so rotated frames are not clipped


def cut_out(path, sparkle_only=False):
    """Return an RGBA image with the green background removed."""
    rgb = np.array(Image.open(path).convert("RGB")).astype(float)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = g - np.maximum(r, b)
    bg = (d >= 50) & (b < 0.55 * g)
    y0, x0 = int(rgb.shape[0] * 0.75), int(rgb.shape[1] * 0.85)
    if sparkle_only:      # watermark touches the character: clear just the star and its halo
        h, w = rgb.shape[:2]
        ys, xs = slice(int(h * 0.80), int(h * 0.88)), slice(int(w * 0.885), int(w * 0.94))
        box = rgb[ys, xs]
        bg[ys, xs] |= (box.min(axis=2) > 120) | (d[ys, xs] >= 20)
    else:                 # corner sparkle
        bg[y0:, x0:] = True
    # drop only large green regions (background, holes between arm/legs); keep small bits
    lab, n = ndimage.label(bg)
    sizes = ndimage.sum(bg, lab, range(1, n + 1))
    big = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s > 150])
    alpha = np.where(big, 0.0, 1.0)
    # soften the edge: pixels next to removed background get partial alpha, then despill
    near = ndimage.binary_dilation(big, iterations=3) & ~big
    soft = np.clip(1 - (d - 12) / 40, 0, 1)
    alpha = np.where(near, np.minimum(alpha, soft), alpha)
    gs = np.where(near, np.minimum(g, np.maximum(r, b) + 6), g)
    if DESPILL:           # green-screen light on skin/hair: pull green back on warm pixels (keeps green eyes, white socks)
        warm = (r > 140) & (r - b > 25) & (alpha > 0)
        gs = np.where(warm & (gs > 0.82 * r), 0.82 * r + (gs - 0.82 * r) * 0.10, gs)
        b = np.where(warm & (b < 0.62 * r), 0.62 * r + (b - 0.62 * r) * 0.3, b)
    out = np.dstack([r, gs, b, alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def bbox(im):
    return im.split()[3].point(lambda v: 255 if v > 20 else 0).getbbox()


def union(b1, b2):
    return (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))


def finish(im):
    a = im.split()[3].point(lambda v: 255 if v > 110 else 0)   # hard edge for the see-through window
    im = im.copy()
    im.putalpha(a)
    return im


def save(out_dir, name, im):
    finish(im).save(os.path.join(out_dir, name + ".png"))
    finish(ImageOps.mirror(im)).save(os.path.join(out_dir, name + "_l.png"))


def walk_frames(src, stand_scale_h):
    """Slice walk.png (6 side-view frames in a row) into aligned transparent frames."""
    im = cut_out(os.path.join(src, "walk.png"), sparkle_only=True)
    a = np.array(im.split()[3]) > 110
    lab, n = ndimage.label(a)
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    comps = [i + 1 for i, sz in enumerate(sizes) if sz > 2000]
    if len(comps) != FRAMES_IN_SHEET:             # neighbours touch: cut the sheet at the emptiest columns
        cols = a.sum(axis=0).astype(float)
        pitch = a.shape[1] / FRAMES_IN_SHEET
        cuts = [0]
        for k in range(1, FRAMES_IN_SHEET):
            lo, hi = int(k * pitch - pitch * 0.2), int(k * pitch + pitch * 0.2)
            cuts.append(lo + int(np.argmin(cols[lo:hi])))
        cuts.append(a.shape[1])
        lab = np.zeros(a.shape, dtype=int)
        comps = []
        for k in range(FRAMES_IN_SHEET):
            part = a.copy()
            part[:, :cuts[k]] = False
            part[:, cuts[k + 1]:] = False
            l2, n2 = ndimage.label(part)
            if n2:
                sz = ndimage.sum(part, l2, range(1, n2 + 1))
                lab[l2 == (int(np.argmax(sz)) + 1)] = k + 1      # keep the biggest piece in this slot
                comps.append(k + 1)
    comps.sort(key=lambda i: np.where(lab == i)[1].mean())          # left to right
    rgba = np.array(im)
    frames = []
    for i in comps:
        m = lab == i
        ys, xs = np.where(m)
        top, bottom = ys.min(), ys.max()
        head = m[top:top + 150]                                       # anchor on the head, not the feet
        hx = np.where(head)[1].mean()
        piece = rgba.copy()
        piece[..., 3] = np.where(m, piece[..., 3], 0)
        frames.append((Image.fromarray(piece, "RGBA"), hx, top, bottom, xs.min(), xs.max()))
    scale = stand_scale_h / max(f[3] - f[2] for f in frames)
    left = max(f[1] - f[4] for f in frames)
    right = max(f[5] - f[1] for f in frames)
    h = max(f[3] - f[2] for f in frames)
    cw, ch = round((left + right) * scale) + 2 * PAD, round(h * scale) + PAD
    out = []
    for img, hx, top, bottom, _, _ in frames:
        crop = img.crop((round(hx - left), top, round(hx + right), bottom + 1))
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(crop, (PAD, ch - crop.height))                   # feet on the bottom edge
        out.append(canvas)
    return out


def build_character(name):
    src, out_dir = os.path.join(SRC, name), os.path.join(OUT, name)
    os.makedirs(out_dir, exist_ok=True)
    meta = {}
    if os.path.exists(os.path.join(src, "character.json")):
        with open(os.path.join(src, "character.json"), encoding="utf-8") as f:
            meta = json.load(f)

    global DESPILL
    DESPILL = bool(meta.get("despill", False))
    stand, drink = (cut_out(os.path.join(src, f + ".png")) for f in ("stand", "drink"))
    box = union(bbox(stand), bbox(drink))
    scale = STAND_H / (box[3] - box[1])
    size = (round((box[2] - box[0]) * scale), STAND_H)

    def prep(im):
        im = im.crop(box).resize(size, Image.LANCZOS)
        canvas = Image.new("RGBA", (size[0] + 2 * PAD, size[1] + PAD), (0, 0, 0, 0))   # margin on sides/top only
        canvas.paste(im, (PAD, PAD))
        return canvas

    s, dk = prep(stand), prep(drink)
    save(out_dir, "stand", s)
    save(out_dir, "drink", dk)

    walk = []
    if os.path.exists(os.path.join(src, "walk.png")):
        for k, f in enumerate(walk_frames(src, STAND_H)):
            save(out_dir, f"walk{k}", f)
            if k not in meta.get("skip_walk", []):
                walk.append(f"walk{k}")
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"display": meta.get("name", name.replace("_", " ").title()), "walk": walk}, f)
    print(f"{name}: stand {s.size}, {len(walk)} walk frames")


def main():
    os.makedirs(OUT, exist_ok=True)
    names = [d for d in sorted(os.listdir(SRC))
             if all(os.path.exists(os.path.join(SRC, d, f)) for f in ("stand.png", "drink.png"))] if os.path.isdir(SRC) else []
    if not names:
        print("No characters found. Put stand.png, drink.png and walk.png in characters/<name>/")
    for name in names:
        build_character(name)


if __name__ == "__main__":
    main()
