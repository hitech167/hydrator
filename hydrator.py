"""Hydrator - a desktop buddy that pops up to remind you to drink water.

Run:  python hydrator.py
- Stays hidden (tray icon near the clock) until it is time to drink.
- Then he walks in from the right edge (only a short way in) and asks you to drink.
- "I drank!" -> he drinks, walks off and hides until the next reminder.
- Tray icon / right-click on him: change the interval, remind now, quit.
"""
import ctypes
import json
import os
import random
import sys
import queue
import time
import tkinter as tk

try:
    import winsound
except ImportError:       # not on Windows
    winsound = None
try:
    import pystray
    from PIL import Image
except ImportError:       # tray icon is optional
    pystray = None

try:                      # crisp rendering on scaled (high-DPI) displays
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

_cfg_dir = os.path.join(os.environ.get("APPDATA") or os.path.dirname(os.path.abspath(__file__)), "Hydrator")
os.makedirs(_cfg_dir, exist_ok=True)
CONFIG = os.path.join(_cfg_dir, "hydrator_config.json")
KEY = "#ff00ff"          # transparent colour key
TICK_MS = 80
WALK = tuple(f"walk{i}" for i in range(5))   # three-quarter walk, bottle hanging in his hand (walk5 is damaged by the watermark)
WALK_SPEED = 10.5            # px per tick while coming in / going out (matches the stride)
WALK_FRAME_TICKS = 2      # ticks each walk frame is shown

W, H = 320, 480          # replaced at start-up to fit the character images


def asset(name):
    """Path of a bundled picture (works from source and from the PyInstaller .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


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
        if not os.path.exists(asset("stand.png")):
            from tkinter import messagebox
            messagebox.showerror("Hydrator", "Character pictures not found.\n\nAdd stand.png, drink.png and walk.png "
                                 "(character on a green background) and run: python make_assets.py\n\nSee README.md.")
            raise SystemExit(1)
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=KEY)
        r.attributes("-transparentcolor", KEY)

        # character pictures (made by make_assets.py); *_l.png are the mirrored, left-facing versions
        self.imgs = {}
        for name in ("stand", "drink", *WALK):
            self.imgs[name, 1] = tk.PhotoImage(file=asset(name + ".png"))
            self.imgs[name, -1] = tk.PhotoImage(file=asset(name + "_l.png"))
        global W, H
        W = max(max(i.width() for i in self.imgs.values()) + 20, 310)   # also wide enough for the bubble
        H = max(i.height() for i in self.imgs.values()) + 120   # room for the speech bubble

        wa = work_area()
        if wa:
            self.left, self.top, self.right, self.bottom = wa
        else:
            self.left, self.top = 0, 0
            self.right, self.bottom = r.winfo_screenwidth(), r.winfo_screenheight() - 48

        self.cfg = {"interval_min": 30, "drank_today": 0, "day": time.strftime("%Y-%m-%d")}
        self.load()

        self.x = float(self.left - W)
        self.y = self.bottom - H
        self.dir = 1
        self.state = "hidden"       # hidden | enter | nudge | happy | exit
        self.state_until = 0.0
        self.target_x = 0.0
        self.cmds = queue.Queue()   # commands from the tray icon thread
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

        self.root.withdraw()
        self.start_tray()
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

    def start_tray(self):
        self.tray = None
        if pystray is None:
            return
        try:
            icon = Image.open(asset("stand.png"))
            icon = icon.crop((0, 0, icon.width, int(icon.width * 0.9)))      # head and shoulders
            icon = icon.resize((64, 64), Image.LANCZOS)
            def cmd(name, arg=None):              # pystray wants callbacks with exactly (icon, item)
                return lambda _icon, _item: self.cmds.put((name, arg))

            intervals = pystray.Menu(*[
                pystray.MenuItem(f"{m} min" + ("  (test)" if m == 1 else ""), cmd("interval", m))
                for m in (1, 15, 30, 45, 60, 90)])
            menu = pystray.Menu(
                pystray.MenuItem(lambda _i: f"Glasses today: {self.cfg['drank_today']}", None, enabled=False),
                pystray.MenuItem("Remind me now", cmd("now")),
                pystray.MenuItem("Remind every...", intervals),
                pystray.MenuItem("Quit", cmd("quit")),
            )
            self.tray = pystray.Icon("Hydrator", icon, "Hydrator", menu)
            self.tray.run_detached()
        except Exception as e:
            self.tray = None
            print("tray icon failed:", repr(e), file=sys.stderr)

    def set_interval(self, m):
        self.cfg["interval_min"] = m
        self.next_due = time.time() + m * 60
        self.save()
        self.build_menu()
        self.say(f"OK, every {m} min!", 3)

    def quit(self):
        self.save()
        if getattr(self, "tray", None):
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    # ---------- actions ----------
    def say(self, text, secs):
        self.msg, self.msg_until = text, time.time() + secs

    def start_nudge(self):
        """Time to drink: walk in from the right edge, only a short way in."""
        if self.state != "hidden":
            return
        self.dir = -1                                        # walking left, onto the screen
        self.x = float(self.right)
        centre = self.right - random.uniform(0.10, 0.14) * (self.right - self.left)
        self.target_x = centre - W / 2
        self.y = self.bottom - H
        self.state = "enter"
        self.msg = ""
        self.place(clamp=False)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()

    def arrived(self):
        self.state = "nudge"
        self.msg = "Time to drink some water!"
        self.msg_until = float("inf")
        self.btn_drank.lift()
        self.btn_later.lift()
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    def leave(self):
        self.msg = ""
        self.dir = 1                                        # back out the way he came (right edge)
        self.state = "exit"

    def drank(self):
        self.cfg["drank_today"] += 1
        self.next_due = time.time() + self.cfg["interval_min"] * 60
        self.save()
        self.build_menu()
        if self.state != "nudge":
            return
        self.state, self.state_until = "happy", time.time() + 2.5
        self.say("Glug glug! Nice!", 2.5)

    def snooze(self):
        self.next_due = time.time() + 5 * 60
        self.leave()

    # ---------- window ----------
    def place(self, clamp=True):
        if clamp:
            self.x = max(self.left, min(self.x, self.right - W))
        self.root.geometry(f"{W}x{H}+{int(self.x)}+{int(self.y)}")

    def on_press(self, e):
        self.drag = (e.x_root - self.x, e.y_root - self.y)

    def on_drag(self, e):
        if self.drag and self.state == "nudge":
            self.x = e.x_root - self.drag[0]
            self.y = max(self.top, min(e.y_root - self.drag[1], self.bottom - H))
            self.place()

    # ---------- drawing ----------
    def draw(self, frame_name, bob=0):
        c = self.canvas
        c.delete("all")
        img = self.imgs[frame_name, self.dir]
        c.create_image(W // 2, H - bob, image=img, anchor="s")
        top = H - bob - img.height()

        showing = self.msg and time.time() < self.msg_until
        if showing:
            self.draw_bubble(top)
        else:
            self.btn_drank.place_forget()
            self.btn_later.place_forget()

    def draw_bubble(self, sprite_top):
        c = self.canvas
        bw, bh = 284, 78 if self.state == "nudge" else 46
        bx0, by0 = (W - bw) // 2, sprite_top - bh - 10
        c.create_rectangle(bx0, by0, bx0 + bw, by0 + bh, fill="#ffffff", outline="#1b3a5c", width=2)
        mid = W // 2
        c.create_polygon(mid - 8, by0 + bh, mid + 8, by0 + bh, mid, by0 + bh + 9,
                         fill="#ffffff", outline="#1b3a5c", width=2)
        c.create_line(mid - 6, by0 + bh, mid + 6, by0 + bh, fill="#ffffff", width=3)
        c.create_text(mid, by0 + 22, text=self.msg, fill="#10243a", font=("Segoe UI", 11, "bold"))
        if self.state == "nudge":
            self.btn_drank.place(x=bx0 + 14, y=by0 + 40, width=122, height=30)
            self.btn_later.place(x=bx0 + 148, y=by0 + 40, width=122, height=30)
        else:
            self.btn_drank.place_forget()
            self.btn_later.place_forget()

    # ---------- main loop ----------
    def tick(self):
        now = time.time()
        self.frame_n += 1

        while not self.cmds.empty():                        # commands from the tray icon
            cmd, arg = self.cmds.get()
            if cmd == "interval":
                self.set_interval(arg)
            elif cmd == "now":
                self.start_nudge()
            elif cmd == "quit":
                return self.quit()

        if self.state == "hidden":
            if now >= self.next_due:
                self.start_nudge()
            self.root.after(250, self.tick)
            return

        frame, bob = "stand", 0
        if self.state in ("enter", "exit"):
            self.x += self.dir * WALK_SPEED
            self.place(clamp=False)
            frame = WALK[(self.frame_n // WALK_FRAME_TICKS) % len(WALK)]
            if self.state == "enter" and (self.x - self.target_x) * self.dir >= 0:
                self.arrived()
            elif self.state == "exit" and (self.x < self.left - W or self.x > self.right):
                self.state = "hidden"
                self.root.withdraw()
                self.root.after(250, self.tick)
                return
        elif self.state == "nudge":
            frame, bob = "stand", 3 if (self.frame_n // 6) % 2 == 0 else 0
        elif self.state == "happy":
            frame = "drink"
            if now >= self.state_until:
                self.leave()

        self.draw(frame, bob)
        self.root.after(TICK_MS, self.tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Hydrator().run()
