"""Hydrator - a tiny pixel desktop buddy that reminds you to drink water.

Run:  python hydrator.py
- It wanders along the bottom of your screen (above the taskbar).
- Every N minutes it stops and asks you to drink; click "I drank" to reset.
- Drag it with the left mouse button. Right-click for interval / quit.
"""
import ctypes
import json
import os
import random
import time
import tkinter as tk

_cfg_dir = os.path.join(os.environ.get("APPDATA") or os.path.dirname(os.path.abspath(__file__)), "Hydrator")
os.makedirs(_cfg_dir, exist_ok=True)
CONFIG = os.path.join(_cfg_dir, "hydrator_config.json")
KEY = "#ff00ff"          # transparent colour key
SCALE = 5                # pixels per sprite pixel
W, H = 260, 190          # window size
TICK_MS = 80

COLORS = {
    "o": "#1b3a5c",  # outline
    "b": "#4db6f5",  # body
    "l": "#bfe9ff",  # highlight
    "e": "#10243a",  # eye
    "m": "#10243a",  # mouth
    "c": "#ff8fa3",  # cheek
    "w": "#ffffff",  # eye shine
}

BODY = [
    ".......oo.......",
    "......obbo......",
    "......obbo......",
    ".....obbbbo.....",
    "....obbbbbbo....",
    "...obbllbbbbo...",
    "...obblbbbbbbo..",
    "..obbbbbbbbbbo..",
    "..obbEbbbbEbbo..",
    "..obbEbbbbEbbo..",
    "..obcbbmmbbcbo..",
    "..obbbbbbbbbbo..",
    "...obbbbbbbbo...",
    "....oobbbbboo...",
]

FEET = {
    "stand": ["....oo....oo....", "................"],
    "step1": ["...oo......oo...", "................"],
    "step2": ["....oo.....oo...", "................"],
}


def build_frame(feet="stand", eyes="open", mouth="smile"):
    rows = [r.ljust(16, ".")[:16] for r in BODY]
    out = []
    for r in rows:
        if eyes == "open":
            r = r.replace("E", "e")
        elif eyes == "closed":
            r = r.replace("E", "b")
        elif eyes == "happy":
            r = r.replace("E", "e")
        out.append(r)
    if eyes == "closed":
        out[8] = out[8][:4] + "ee" + out[8][6:10] + "ee" + out[8][12:]
    if eyes == "happy":
        out[9] = out[9].replace("e", "b")
    if mouth == "open":
        out[10] = out[10].replace("mm", "ee")
    out += [r.ljust(16, ".")[:16] for r in FEET[feet]]
    return out


FRAMES = {
    "idle": build_frame("stand"),
    "blink": build_frame("stand", eyes="closed"),
    "step1": build_frame("step1"),
    "step2": build_frame("step2"),
    "happy": build_frame("stand", eyes="happy", mouth="open"),
    "nudge": build_frame("stand", mouth="open"),
}


def work_area():
    """Return (left, top, right, bottom) of the usable desktop (excludes taskbar)."""
    class RECT(ctypes.Structure):
        _fields_ = [(n, ctypes.c_long) for n in ("left", "top", "right", "bottom")]
    r = RECT()
    try:
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


class Hydrator:
    def __init__(self):
        self.root = tk.Tk()
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=KEY)
        r.attributes("-transparentcolor", KEY)

        wa = work_area()
        if wa:
            self.left, self.top, self.right, self.bottom = wa
        else:
            self.left, self.top = 0, 0
            self.right, self.bottom = r.winfo_screenwidth(), r.winfo_screenheight() - 48

        self.cfg = {"interval_min": 30, "drank_today": 0, "day": time.strftime("%Y-%m-%d")}
        self.load()

        self.x = float(random.randint(self.left + 50, self.right - W - 50))
        self.y = self.bottom - H
        self.dir = 1
        self.state = "idle"         # idle | walk | nudge | happy
        self.state_until = time.time() + 2
        self.frame_n = 0
        self.next_due = time.time() + self.cfg["interval_min"] * 60
        self.msg = ""
        self.msg_until = 0.0
        self.drag = None

        self.canvas = tk.Canvas(r, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.btn_drank = tk.Button(r, text="I drank!", command=self.drank, bg="#4db6f5",
                                   fg="#10243a", relief="flat", font=("Segoe UI", 9, "bold"),
                                   padx=8, cursor="hand2")
        self.btn_later = tk.Button(r, text="Later (5m)", command=self.snooze, bg="#e8eef4",
                                   fg="#10243a", relief="flat", font=("Segoe UI", 9),
                                   padx=6, cursor="hand2")

        self.menu = tk.Menu(r, tearoff=0)
        self.build_menu()
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.canvas.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

        self.place()
        self.tick()

    # ---------- persistence ----------
    def load(self):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass
        if self.cfg.get("day") != time.strftime("%Y-%m-%d"):
            self.cfg["day"] = time.strftime("%Y-%m-%d")
            self.cfg["drank_today"] = 0

    def save(self):
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f)
        except Exception:
            pass

    # ---------- menu ----------
    def build_menu(self):
        self.menu.delete(0, "end")
        self.menu.add_command(label=f"Glasses today: {self.cfg['drank_today']}", state="disabled")
        self.menu.add_separator()
        sub = tk.Menu(self.menu, tearoff=0)
        for m in (1, 15, 30, 45, 60, 90):
            label = f"{m} min" + ("  (test)" if m == 1 else "")
            sub.add_command(label=label, command=lambda m=m: self.set_interval(m))
        self.menu.add_cascade(label=f"Remind every {self.cfg['interval_min']} min", menu=sub)
        self.menu.add_command(label="Remind me now", command=self.start_nudge)
        self.menu.add_command(label="I drank", command=self.drank)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

    def set_interval(self, m):
        self.cfg["interval_min"] = m
        self.next_due = time.time() + m * 60
        self.save()
        self.build_menu()
        self.say(f"OK, every {m} min!", 3)

    def quit(self):
        self.save()
        self.root.destroy()

    # ---------- actions ----------
    def say(self, text, secs):
        self.msg, self.msg_until = text, time.time() + secs

    def start_nudge(self):
        self.state = "nudge"
        self.msg = "Time to drink some water!"
        self.msg_until = float("inf")
        self.btn_drank.lift()
        self.btn_later.lift()

    def drank(self):
        self.cfg["drank_today"] += 1
        self.next_due = time.time() + self.cfg["interval_min"] * 60
        self.save()
        self.build_menu()
        self.state, self.state_until = "happy", time.time() + 2.5
        self.say("Glug glug! Nice!", 2.5)

    def snooze(self):
        self.next_due = time.time() + 5 * 60
        self.state, self.state_until = "idle", time.time() + 1
        self.say("Ok, 5 more minutes...", 2)

    # ---------- window ----------
    def place(self):
        self.x = max(self.left, min(self.x, self.right - W))
        self.root.geometry(f"{W}x{H}+{int(self.x)}+{int(self.y)}")

    def on_press(self, e):
        self.drag = (e.x_root - self.x, e.y_root - self.y)

    def on_drag(self, e):
        if self.drag:
            self.x = e.x_root - self.drag[0]
            self.y = max(self.top, min(e.y_root - self.drag[1], self.bottom - H))
            self.place()

    # ---------- drawing ----------
    def draw(self, frame_name):
        c = self.canvas
        c.delete("all")
        rows = FRAMES[frame_name]
        ox = (W - 16 * SCALE) // 2
        oy = H - len(rows) * SCALE - 2
        for ry, row in enumerate(rows):
            if self.dir < 0:
                row = row[::-1]
            for rx, ch in enumerate(row):
                col = COLORS.get(ch)
                if col:
                    x0, y0 = ox + rx * SCALE, oy + ry * SCALE
                    c.create_rectangle(x0, y0, x0 + SCALE, y0 + SCALE, fill=col, outline=col)

        showing = self.msg and time.time() < self.msg_until
        if showing:
            self.draw_bubble(oy)
        else:
            self.btn_drank.place_forget()
            self.btn_later.place_forget()

    def draw_bubble(self, sprite_top):
        c = self.canvas
        bw, bh = 220, 62 if self.state == "nudge" else 38
        bx0, by0 = (W - bw) // 2, sprite_top - bh - 10
        c.create_rectangle(bx0, by0, bx0 + bw, by0 + bh, fill="#ffffff", outline="#1b3a5c", width=2)
        mid = W // 2
        c.create_polygon(mid - 8, by0 + bh, mid + 8, by0 + bh, mid, by0 + bh + 9,
                         fill="#ffffff", outline="#1b3a5c", width=2)
        c.create_line(mid - 6, by0 + bh, mid + 6, by0 + bh, fill="#ffffff", width=3)
        c.create_text(mid, by0 + 15, text=self.msg, fill="#10243a", font=("Segoe UI", 10, "bold"))
        if self.state == "nudge":
            self.btn_drank.place(x=bx0 + 12, y=by0 + 30, width=92, height=24)
            self.btn_later.place(x=bx0 + 112, y=by0 + 30, width=96, height=24)
        else:
            self.btn_drank.place_forget()
            self.btn_later.place_forget()

    # ---------- main loop ----------
    def tick(self):
        now = time.time()
        self.frame_n += 1

        if self.state != "nudge" and now >= self.next_due:
            self.start_nudge()

        if self.state in ("idle", "walk") and now >= self.state_until:
            if self.state == "idle" and random.random() < 0.7:
                self.state = "walk"
                self.dir = random.choice((-1, 1))
                self.state_until = now + random.uniform(2, 6)
            else:
                self.state = "idle"
                self.state_until = now + random.uniform(2, 5)
        elif self.state == "happy" and now >= self.state_until:
            self.state, self.state_until = "idle", now + 2

        if self.state == "walk":
            self.x += self.dir * 3
            if self.x <= self.left or self.x >= self.right - W:
                self.dir *= -1
            self.place()
            frame = "step1" if (self.frame_n // 3) % 2 == 0 else "step2"
        elif self.state == "happy":
            frame = "happy"
        elif self.state == "nudge":
            frame = "nudge" if (self.frame_n // 6) % 2 == 0 else "idle"
        else:
            frame = "blink" if self.frame_n % 50 < 3 else "idle"

        self.draw(frame)
        self.root.after(TICK_MS, self.tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Hydrator().run()
