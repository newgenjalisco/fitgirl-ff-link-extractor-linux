# FitGirl FF Link Extractor | Linux port

This is a Linux port of [zouhirdev/fitgirl-ff-link-extractor](https://github.com/zouhirdev/fitgirl-ff-link-extractor).
The code is essentially the same, this fork only makes it work natively on
Linux and adds brave origin support.

**How to use the app:** follow the original project's README -> <https://github.com/zouhirdev/fitgirl-ff-link-extractor>

## What this fork changes

- Changed to work for Linux: detects Chrome, Edge, Brave, and Firefox installs,
  including Flatpak paths.
- Detects Linux brave origin binaries (`/usr/bin`, `/etc/alternatives`,
  `/opt/brave.com`) with a `PATH` fallback.

All credit for the original program goes to
[zouhirdev](https://github.com/zouhirdev/fitgirl-ff-link-extractor).

## Linux instructions

### Requirements

- Python 3.11+ with Tkinter:
  - Debian/Ubuntu: `sudo apt install python3 python3-venv python3-tk`
  - Arch: `sudo pacman -S python tk`
  - Fedora: `sudo dnf install python3 python3-tkinter`
- Supported browsers: Chrome, Brave, Edge, or Firefox.

### Run from source

```bash
git clone https://github.com/newgenjalisco/fitgirl-ff-link-extractor-linux.git
cd fitgirl-ff-link-extractor-linux

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python ff_grabber.py
```

### Build a standalone Linux binary

```bash
source .venv/bin/activate
pip install pyinstaller
pyinstaller --onefile --name="FitGirl_FF_Link_Extractor-linux" ff_grabber.py
./dist/FitGirl_FF_Link_Extractor-linux
```
