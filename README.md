# Hydrator

A tiny desktop buddy that reminds you to drink water.

He stays hidden (tray icon near the clock) until it is time to drink. Then he walks in from the right
edge of the screen, stops above the taskbar and asks you to drink. Click **I drank!** and he drinks,
walks back out and hides until the next reminder.

## Run

Requires Windows and Python 3.9+.

```
pip install -r requirements.txt
python hydrator.py
```

Right-click the tray icon (click the **^** arrow near the clock if it is hidden) to:

- trigger **Remind me now**
- change **Remind every...** (15 – 90 minutes; "1 min" is for testing)
- see the glasses count for today, or **Quit**

Settings are saved in `%APPDATA%\Hydrator`.

## Character pictures

The character images are **not included** in this repository. Make your own:

1. Generate pictures of your character on a plain bright green (`#00FF00`) background, with an image tool:
   - `stand.png` - standing, holding a water bottle
   - `drink.png` - drinking from the bottle
   - `walk.png` - a 6-frame walk cycle in one row (three-quarter view, bottle in hand)
2. Put them next to `hydrator.py`.
3. Run `python make_assets.py`. It cuts out the green background and writes small frames into `assets/`.
4. Run `python hydrator.py`.

Please use original characters, or characters you have the rights to, for anything you share.

## Build an .exe

```
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name Hydrator --add-data "assets;assets" --hidden-import pystray._win32 hydrator.py
```

The result is `dist/Hydrator.exe`.
