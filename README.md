# Hydrator

A tiny pixel water-drop that walks along your desktop and reminds you to drink water.

## Download (Windows)

Grab `Hydrator.exe` from the [Releases](../../releases) page and double-click it. No install needed.

> Windows may show "Windows protected your PC" because the app is not code-signed.
> Click **More info → Run anyway**.

## Use

- It wanders above your taskbar. Drag it anywhere with the left mouse button.
- Every N minutes (default 30) it asks you to drink. Click **I drank!** to reset the timer, or **Later (5m)** to snooze.
- Right-click it to change the interval, trigger a reminder, see today's glass count, or quit.
- Settings are saved in `%APPDATA%\Hydrator`.

## Run from source

Requires Python 3.9+ (Tkinter is included on Windows).

```
python hydrator.py
```

## Build the .exe

```
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name Hydrator hydrator.py
```

The result is `dist/Hydrator.exe`.
