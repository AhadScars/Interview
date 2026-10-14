# -*- coding: utf-8 -*-
"""Veil: a private window. Screen-capture APIs skip it, and it has no taskbar button.

Run with pythonw.exe (the desktop shortcut does this). Ctrl+Alt+V hides and shows it.
PC opens This PC inside the same window.
Shot takes a silent full-screen or region screenshot.
If ChatGPT or Gemini is open in this window, the shot is pasted into its message box.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import traceback
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote

APP = Path(os.environ.get("APPDATA", str(Path.home()))) / "Veil"
NOTES = APP / "notes.txt"
SHOTS = Path(os.environ.get("USERPROFILE") or str(Path.home())) / "Pictures" / "Screenshots"
LOG = APP / "veil.log"
MUTEX_NAME = "Local\\VeilPrivateWindow"
WINDOW_TITLE = "Veil"

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
EM_SETCUEBANNER = 0x1501
ERROR_ALREADY_EXISTS = 183

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


VK_CONTROL = 0x11
VK_V = 0x56
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

CHATGPT_FOCUS_JS = """
(function () {
  var el = document.querySelector('#prompt-textarea')
    || document.querySelector('div.ProseMirror[contenteditable="true"]')
    || document.querySelector('[contenteditable="true"][role="textbox"]')
    || document.querySelector('textarea');
  if (!el) return 'missing';
  el.focus();
  try {
    var sel = window.getSelection();
    var range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (e) {}
  return 'ok';
})()
"""

GEMINI_FOCUS_JS = """
(function () {
  var selectors = [
    'rich-textarea .ql-editor[contenteditable="true"]',
    'div.ql-editor[contenteditable="true"]',
    '[aria-label="Enter a prompt here"]',
    'rich-textarea [contenteditable="true"]',
    'div[contenteditable="true"][role="textbox"]'
  ];
  var el = null;
  for (var i = 0; i < selectors.length; i++) {
    var found = document.querySelector(selectors[i]);
    if (found) { el = found; break; }
  }
  if (!el) return 'missing';
  el.focus();
  try {
    var sel = window.getSelection();
    var range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (e) {}
  return 'ok';
})()
"""


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


def _bind():
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long


_bind()

_mutex = None
_delete_tab = None
_tab_failed = False
_form = None
_window = None
_page_html = ""
_refs = []
_chosen_hotkey = "Ctrl+Alt+V"
_test = os.environ.get("VEIL_TEST") == "1"


def log(message):
    try:
        APP.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except Exception:
        pass


def as_hwnd(value):
    if hasattr(value, "ToInt64"):
        value = value.ToInt64()
    return int(value) & ((1 << 64) - 1)


def hide_console():
    console = kernel32.GetConsoleWindow()
    if console:
        user32.SetWindowDisplayAffinity(console, WDA_EXCLUDEFROMCAPTURE)
        user32.ShowWindow(console, 0)


def focus_existing():
    for _ in range(30):
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 5)
            user32.SetForegroundWindow(hwnd)
            return
        threading.Event().wait(0.1)


def claim_single_instance():
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        focus_existing()
        sys.exit(0)


def _make_guid(text):
    guid = GUID()
    if ole32.CLSIDFromString(text, ctypes.byref(guid)) != 0:
        raise OSError("bad guid")
    return guid


def taskbar_delete():
    global _delete_tab, _tab_failed
    if _delete_tab is not None or _tab_failed:
        return _delete_tab

    try:
        ole32.CoInitialize(None)
        clsid = _make_guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")
        iid = _make_guid("{56FDF342-FD6D-11d0-958A-006097C9A090}")
        com = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(com))
        if hr != 0 or not com.value:
            raise OSError("CoCreateInstance 0x%08X" % (hr & 0xFFFFFFFF))
        vtable = ctypes.cast(
            ctypes.cast(com, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr_init = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
        delete = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND)(vtable[5])
        if hr_init(com) != 0:
            raise OSError("ITaskbarList.HrInit failed")

        def _call(hwnd):
            return delete(com, hwnd)

        _delete_tab = _call
        log("taskbar DeleteTab ready")
    except Exception:
        _tab_failed = True
        log(traceback.format_exc())
        return None
    return _delete_tab


def shield(hwnd):
    if not hwnd:
        return False
    return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def child_hwnds(parent):
    found = []

    def _cb(hwnd, _lp):
        found.append(as_hwnd(hwnd))
        return True

    callback = WNDENUMPROC(_cb)
    user32.EnumChildWindows(parent, callback, 0)
    return found


def ensure_toolwindow(hwnd):
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    updated = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if updated != ex:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, updated)
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    return updated


def conceal(hwnd):
    ensure_toolwindow(hwnd)
    delete = taskbar_delete()
    if delete:
        delete(hwnd)


def shield_all(force_tab=False):
    pid = kernel32.GetCurrentProcessId()
    tops = []

    def _cb(hwnd, _lp):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            tops.append(as_hwnd(hwnd))
        return True

    callback = WNDENUMPROC(_cb)
    user32.EnumWindows(callback, 0)
    for hwnd in tops:
        shield(hwnd)
        for child in child_hwnds(hwnd):
            shield(child)
        if user32.IsWindowVisible(hwnd) and class_name(hwnd).startswith("WindowsForms"):
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            drifted = (ex & WS_EX_TOOLWINDOW) == 0 or (ex & WS_EX_APPWINDOW) != 0
            if drifted or force_tab:
                conceal(hwnd)


def write_ready():
    if not _test or _form is None:
        return
    try:
        hwnd = as_hwnd(_form.Handle)
        affinity = wintypes.DWORD()
        user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        path = Path(os.environ.get("TEMP", ".")) / "veil-ready.txt"
        path.write_text(
            "pid=%s\nhwnd=%s\naffinity=%s\nexstyle=%s\ntab=%s\n"
            % (os.getpid(), hwnd, int(affinity.value), ex, "fail" if _tab_failed else "ok"),
            encoding="utf-8",
        )
    except Exception:
        log(traceback.format_exc())


def normalize_url(raw):
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if " " in text or "." not in text:
        return "https://www.google.com/search?q=" + quote(text)
    return "https://" + text


HOME_HTML = """<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #14161c;
    --card: #1c1f27;
    --ink: #ece7dc;
    --muted: #9a958a;
    --line: #31363f;
    --brass: #e0b15a;
    --ok: #8fceab;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", sans-serif; }
  .wrap {
    height: 100%; display: flex; flex-direction: column; overflow: auto;
    padding: clamp(12px, 3vw, 22px); gap: clamp(8px, 2vw, 12px);
  }
  .kicker { color: var(--brass); letter-spacing: .14em; font-size: clamp(10px, 2vw, 11px); }
  h1 { font-size: clamp(18px, 4.4vw, 28px); font-weight: 600; margin: 2px 0 0; letter-spacing: -0.03em; }
  .status { color: var(--ok); font-size: clamp(12.5px, 2.5vw, 14px); line-height: 1.45; margin-top: 8px; }
  .hint { color: var(--muted); font-size: clamp(12px, 2.4vw, 13.5px); line-height: 1.5; margin: 8px 0 0; }
  kbd { font-family: Consolas, monospace; background: #2a2e38; border: 1px solid #3c4250; border-radius: 4px; padding: 1px 6px; color: var(--ink); }
  textarea {
    flex: 1 1 auto; width: 100%; min-height: 96px; resize: none; border: 1px solid var(--line);
    background: var(--card); color: var(--ink); border-radius: 12px; padding: clamp(10px, 2vw, 16px);
    font: clamp(14px, 2.6vw, 16px)/1.5 "Segoe UI", sans-serif; outline: none;
  }
  @media (max-height: 560px) {
    h1 { font-size: 18px; }
    .status, .hint { margin-top: 4px; }
    textarea { min-height: 72px; }
  }
  textarea:focus { border-color: #8a7040; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  button.link {
    flex: 1 1 7.5rem; min-height: 34px; text-align: center;
    background: transparent; color: var(--ink); border: 1px solid var(--line);
    border-radius: 999px; padding: 7px 12px; font: 600 13px "Segoe UI", sans-serif; cursor: pointer;
  }
  button.link:hover { border-color: var(--brass); color: var(--brass); }
  button.link:focus-visible { outline: 1px solid var(--brass); outline-offset: 2px; }
</style>
</head>
<body>
  <div class="wrap">
    <div>
      <div class="kicker">PRIVATE WINDOW</div>
      <h1>Only on your screen</h1>
      <div class="status">Screen share skips this window. It stays off the taskbar and Alt+Tab.</div>
      <p class="hint">Press <kbd>__HOTKEY__</kbd> to hide or show it. PC browses this computer. Shot takes the full screen or a region, with no notification. When ChatGPT or Gemini is open here, the image is pasted into the message box.</p>
    </div>
    <textarea id="notes" spellcheck="false" placeholder="Write notes here."></textarea>
    <div class="row">
      <button class="link" data-url="https://chatgpt.com">ChatGPT</button>
      <button class="link" data-url="https://gemini.google.com">Gemini</button>
      <button class="link" data-url="https://www.google.com">Google</button>
    </div>
  </div>
  <script>
    const notes = document.getElementById("notes");
    let timer = null;
    function whenReady(fn) {
      if (window.pywebview && window.pywebview.api) fn();
      else window.addEventListener("pywebviewready", fn);
    }
    whenReady(async () => {
      try { notes.value = await window.pywebview.api.load_notes(); } catch (e) {}
      notes.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => window.pywebview.api.save_notes(notes.value), 250);
      });
    });
    document.querySelectorAll("button.link").forEach((button) => {
      button.addEventListener("click", () => window.pywebview.api.go(button.dataset.url));
    });
  </script>
</body>
</html>
"""


class Api:
    def load_notes(self):
        try:
            return NOTES.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except Exception:
            log(traceback.format_exc())
            return ""

    def save_notes(self, text):
        try:
            if not isinstance(text, str):
                text = str(text)
            text = text[:2_000_000]
            NOTES.parent.mkdir(parents=True, exist_ok=True)
            temp = NOTES.with_suffix(".tmp")
            temp.write_text(text, encoding="utf-8")
            temp.replace(NOTES)
            return True
        except Exception:
            log(traceback.format_exc())
            return False

    def go(self, url):
        target = normalize_url(url)
        if target and _window is not None:
            close_pc()
            _window.load_url(target)
        return True


def _folder_target(text):
    raw = (text or "").strip().strip('"')
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in "\\/":
        return raw.replace("/", "\\")
    if raw.startswith("\\\\"):
        return raw
    return ""


def navigate(url=None):
    form = _form
    if form is None:
        return
    raw = form._veil_box.Text if url is None else url
    folder = _folder_target(raw)
    if folder:
        close_shot()
        open_pc(folder)
        return
    close_shot()
    close_pc()
    target = normalize_url(raw)
    if not target:
        return
    try:
        core = form.webview.CoreWebView2
        if core is None:
            threading.Thread(target=lambda: _window.load_url(target), daemon=True).start()
        else:
            core.Navigate(target)
        form._veil_box.Text = target
    except Exception:
        log(traceback.format_exc())


def _ui_scale(form):
    try:
        return max(1.0, float(form.DeviceDpi) / 96.0)
    except Exception:
        return 1.0


def layout_bar(*_):
    form = _form
    if form is None or getattr(form, "_veil_laying", False):
        return
    menu = getattr(form, "_veil_shot_menu", None)
    if menu is not None and menu.Visible:
        menu.Visible = False
    panel = form._veil_panel
    width = int(panel.ClientSize.Width)
    if width < 80:
        return
    scale = _ui_scale(form)

    def px(value):
        return max(1, int(round(value * scale)))

    pad = px(8)
    gap = px(6)
    row_h = px(32)
    back_w = px(36)
    go_w = px(48)
    home_w = px(62)
    pin_w = px(68)
    pc_w = px(46)
    shot_w = px(58)
    hide_w = px(58)
    url_min = px(128)
    one_row = (
        pad * 2 + back_w + go_w + home_w + pc_w + shot_w + pin_w + hide_w + gap * 7 + url_min
    )
    two_rows = width < one_row
    row2_need = pad * 2 + home_w + pc_w + shot_w + pin_w + hide_w + gap * 4
    three_rows = two_rows and width < row2_need
    rows = 3 if three_rows else (2 if two_rows else 1)
    form._veil_laying = True
    try:
        panel.Height = pad * 2 + row_h * rows + gap * (rows - 1)
        back = form._veil_back
        box = form._veil_box
        go = form._veil_go
        home = form._veil_home
        pc = form._veil_pc
        shot = form._veil_shot
        pin = form._veil_pin
        hide = form._veil_hide
        if two_rows:
            back.SetBounds(pad, pad, back_w, row_h)
            go_x = width - pad - go_w
            go.SetBounds(go_x, pad, go_w, row_h)
            url_left = pad + back_w + gap
            box.SetBounds(url_left, pad + px(2), max(px(48), go_x - gap - url_left), row_h - px(4))
            second = pad + row_h + gap
            if three_rows:
                hide_x = width - pad - hide_w
                hide.SetBounds(hide_x, second, hide_w, row_h)
                pin_x = hide_x - gap - pin_w
                pin.SetBounds(pin_x, second, pin_w, row_h)
                home.SetBounds(pin_x - gap - home_w, second, home_w, row_h)
                third = second + row_h + gap
                shot.SetBounds(width - pad - shot_w, third, shot_w, row_h)
                pc.SetBounds(width - pad - shot_w - gap - pc_w, third, pc_w, row_h)
            else:
                hide_x = width - pad - hide_w
                hide.SetBounds(hide_x, second, hide_w, row_h)
                pin_x = hide_x - gap - pin_w
                pin.SetBounds(pin_x, second, pin_w, row_h)
                shot_x = pin_x - gap - shot_w
                shot.SetBounds(shot_x, second, shot_w, row_h)
                pc_x = shot_x - gap - pc_w
                pc.SetBounds(pc_x, second, pc_w, row_h)
                home.SetBounds(pc_x - gap - home_w, second, home_w, row_h)
        else:
            back.SetBounds(pad, pad, back_w, row_h)
            right = width - pad
            for button, button_w in (
                (hide, hide_w),
                (pin, pin_w),
                (shot, shot_w),
                (pc, pc_w),
                (home, home_w),
                (go, go_w),
            ):
                right -= button_w
                button.SetBounds(right, pad, button_w, row_h)
                right -= gap
            url_left = pad + back_w + gap
            box.SetBounds(url_left, pad + px(2), max(px(48), right - url_left), row_h - px(4))
    finally:
        form._veil_laying = False


def paint_button(button, label):
    import System.Windows.Forms as WinForms
    from System.Drawing import Color

    button.Text = label
    button.FlatStyle = WinForms.FlatStyle.Flat
    button.FlatAppearance.BorderSize = 0
    button.BackColor = Color.FromArgb(255, 36, 34, 30)
    button.ForeColor = Color.FromArgb(255, 236, 228, 210)
    button.Cursor = WinForms.Cursors.Hand
    button.TabStop = False
    button.Font = _form._veil_font
    return button


_place_actions = []


def paint_pc(on):
    form = _form
    if form is None:
        return
    from System.Drawing import Color

    button = form._veil_pc
    if on:
        button.BackColor = Color.FromArgb(255, 224, 177, 90)
        button.ForeColor = Color.FromArgb(255, 28, 24, 16)
    else:
        button.BackColor = Color.FromArgb(255, 36, 34, 30)
        button.ForeColor = Color.FromArgb(255, 236, 228, 210)
    form._veil_pc_on = on


def _on_place(name):
    form = _form
    if form is None or not form.IsHandleCreated or not name:
        return
    from System import Action

    def apply(name=name):
        current = _form
        if current is not None and getattr(current, "_veil_pc_on", False):
            current._veil_box.Text = name

    action = Action(apply)
    _place_actions.append(action)
    if len(_place_actions) > 20:
        del _place_actions[:-10]
    try:
        form.BeginInvoke(action)
    except Exception:
        log(traceback.format_exc())


def open_pc(path=None):
    form = _form
    if form is None or _test or form._veil_files is None:
        return
    host = form._veil_files_panel
    close_shot()
    hide_shot_menu()
    if not getattr(form, "_veil_pc_on", False):
        current = form._veil_box.Text
        if not _folder_target(current):
            form._veil_web_text = current
    try:
        form.webview.Visible = False
        host.Visible = True
        host.BringToFront()
        form._veil_panel.BringToFront()
        form.PerformLayout()
        form._veil_files.open(host, path)
    except Exception:
        log(traceback.format_exc())
        host.Visible = False
        try:
            form.webview.Visible = True
            form._veil_panel.BringToFront()
        except Exception:
            log(traceback.format_exc())
        paint_pc(False)
        return
    paint_pc(True)
    if path:
        form._veil_box.Text = path
    try:
        shield_all()
    except Exception:
        log(traceback.format_exc())


def close_pc():
    form = _form
    if form is None or not getattr(form, "_veil_pc_on", False):
        return
    try:
        form._veil_files.hide()
        form._veil_files_panel.Visible = False
        form.webview.Visible = True
        form._veil_panel.BringToFront()
        form._veil_box.Text = getattr(form, "_veil_web_text", "") or ""
    except Exception:
        log(traceback.format_exc())
    paint_pc(False)


def toggle_pc():
    if getattr(_form, "_veil_pc_on", False):
        close_pc()
        return
    open_pc(None)


def hide_shot_menu():
    form = _form
    menu = None if form is None else getattr(form, "_veil_shot_menu", None)
    if menu is not None:
        menu.Visible = False


def close_shot():
    form = _form
    if form is None or not getattr(form, "_veil_shot_on", False):
        return
    form._veil_shot_on = False
    try:
        form._veil_shot_panel.Visible = False
        picture = form._veil_shot_image
        image = picture.Image
        picture.Image = None
        if image is not None:
            image.Dispose()
        if not getattr(form, "_veil_pc_on", False):
            form.webview.Visible = True
            form._veil_panel.BringToFront()
    except Exception:
        log(traceback.format_exc())


def show_shot(path, bitmap):
    form = _form
    if form is None:
        if bitmap is not None:
            bitmap.Dispose()
        return
    close_pc()
    hide_shot_menu()
    try:
        previous = form._veil_shot_image.Image
        form._veil_shot_image.Image = bitmap
        if previous is not None:
            previous.Dispose()
        form._veil_shot_label.Text = path.name + "   ·   Pictures\\Screenshots"
        form.webview.Visible = False
        form._veil_shot_panel.Visible = True
        form._veil_shot_panel.BringToFront()
        form._veil_panel.BringToFront()
        form._veil_shot_on = True
        form._veil_box.Text = str(path)
    except Exception:
        log(traceback.format_exc())
        if bitmap is not None:
            bitmap.Dispose()


def _page_url(form):
    try:
        source = form.webview.Source
        if source is not None:
            return str(source.AbsoluteUri)
    except Exception:
        pass
    try:
        return form._veil_box.Text or ""
    except Exception:
        return ""


def _composer_script(form):
    if form is None or getattr(form, "_veil_pc_on", False):
        return None
    url = _page_url(form).lower()
    if "chatgpt.com" in url or "chat.openai.com" in url:
        return CHATGPT_FOCUS_JS
    if "gemini.google.com" in url:
        return GEMINI_FOCUS_JS
    return None


def _copy_image(bitmap):
    import System.Windows.Forms as WinForms
    from System.Drawing.Imaging import ImageFormat
    from System.IO import MemoryStream

    stream = MemoryStream()
    try:
        bitmap.Save(stream, ImageFormat.Png)
        stream.Position = 0
        data = WinForms.DataObject()
        data.SetImage(bitmap)
        data.SetData("PNG", False, stream)
        WinForms.Clipboard.SetDataObject(data, True)
    finally:
        stream.Dispose()


def _focus_veil(form):
    hwnd = as_hwnd(form.Handle)
    foreground = user32.GetForegroundWindow()
    current = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = False
    if other and other != current:
        attached = bool(user32.AttachThreadInput(current, other, True))
    try:
        user32.SetForegroundWindow(hwnd)
        form.Activate()
        form.webview.Focus()
    finally:
        if attached:
            user32.AttachThreadInput(current, other, False)


def _send_ctrl_v():
    keys = (INPUT * 4)()
    sequence = (
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )
    for index, (vk, flags) in enumerate(sequence):
        key = KEYBDINPUT()
        key.wVk = vk
        key.dwFlags = flags
        keys[index].type = INPUT_KEYBOARD
        keys[index].union.ki = key
    sent = user32.SendInput(4, keys, ctypes.sizeof(INPUT))
    if sent != 4:
        log("paste keys sent %s" % sent)


def _queue_composer_paste(form, bitmap, script):
    import System.Windows.Forms as WinForms

    close_shot()
    form.webview.Visible = True
    form._veil_panel.BringToFront()
    _focus_veil(form)
    try:
        form.webview.CoreWebView2.ExecuteScriptAsync(script)
    except Exception:
        log(traceback.format_exc())
    previous = getattr(form, "_veil_paste_timer", None)
    if previous is not None:
        try:
            previous.Stop()
            previous.Dispose()
        except Exception:
            pass
    form._veil_paste_gen = getattr(form, "_veil_paste_gen", 0) + 1
    generation = form._veil_paste_gen
    timer = WinForms.Timer()
    timer.Interval = 400

    def tick(sender, args):
        timer.Stop()
        try:
            timer.Dispose()
        except Exception:
            pass
        if getattr(form, "_veil_paste_gen", 0) != generation:
            try:
                bitmap.Dispose()
            except Exception:
                pass
            return
        try:
            _focus_veil(form)
            _send_ctrl_v()
            log("composer paste")
        except Exception:
            log(traceback.format_exc())
        try:
            bitmap.Dispose()
        except Exception:
            pass

    timer.Tick += tick
    form._veil_paste_timer = timer
    _refs.append(tick)
    timer.Start()


def take_shot(rect):
    from veil_shot import save_capture

    hide_shot_menu()
    try:
        path, bitmap = save_capture(rect[0], rect[1], rect[2], rect[3], SHOTS)
    except Exception:
        log(traceback.format_exc())
        if _form is not None:
            _form._veil_box.Text = "Couldn't save the screenshot"
        return
    if path is None:
        return
    log("shot " + path.name)
    form = _form
    script = _composer_script(form)
    if script:
        try:
            _copy_image(bitmap)
            _queue_composer_paste(form, bitmap, script)
            return
        except Exception:
            log(traceback.format_exc())
    show_shot(path, bitmap)


def take_full_shot():
    from veil_shot import virtual_screen

    take_shot(virtual_screen())


def take_region_shot():
    form = _form
    if form is None or _test:
        return
    hide_shot_menu()
    picker = form._veil_picker
    if picker is None:
        from veil_shot import RegionPick

        picker = RegionPick(lambda rect: take_shot(rect), lambda: None)
        form._veil_picker = picker
        _refs.append(picker)
    if picker.active:
        return
    picker.start()


def cancel_region():
    form = _form
    picker = None if form is None else getattr(form, "_veil_picker", None)
    if picker is not None and picker.active:
        picker.on_cancel = None
        picker.cancel()


def arm():
    global _form
    import System.Windows.Forms as WinForms
    from System.Drawing import Color, ContentAlignment, Font, Size

    form = _form
    font = Font("Segoe UI", 9.0)
    form._veil_font = font
    form.BackColor = Color.FromArgb(255, 20, 21, 26)

    panel = WinForms.Panel()
    panel.Height = 48
    panel.Dock = WinForms.DockStyle.Top
    panel.BackColor = Color.FromArgb(255, 20, 21, 26)
    form.Controls.Add(panel)
    panel.BringToFront()

    box = WinForms.TextBox()
    box.BorderStyle = WinForms.BorderStyle.FixedSingle
    box.BackColor = Color.FromArgb(255, 16, 17, 22)
    box.ForeColor = Color.FromArgb(255, 236, 231, 220)
    box.Font = font
    box.AutoSize = False

    def on_enter(sender, args):
        if args.KeyCode == WinForms.Keys.Enter:
            args.SuppressKeyPress = True
            args.Handled = True
            navigate()

    box.KeyDown += on_enter

    back = WinForms.Button()
    go = WinForms.Button()
    home = WinForms.Button()
    pin = WinForms.Button()
    pc = WinForms.Button()
    shot = WinForms.Button()
    hide = WinForms.Button()
    for button, label in (
        (back, "←"),
        (go, "Go"),
        (home, "Home"),
        (pin, "Unpin"),
        (pc, "PC"),
        (shot, "Shot"),
        (hide, "Hide"),
    ):
        paint_button(button, label)
        panel.Controls.Add(button)
    panel.Controls.Add(box)

    def on_go(sender, args):
        hide_shot_menu()
        navigate()

    def on_home(sender, args):
        hide_shot_menu()
        close_shot()
        close_pc()
        box.Text = ""
        try:
            form.browser.load_html(_page_html, None)
        except Exception:
            log(traceback.format_exc())

    def on_back(sender, args):
        hide_shot_menu()
        if getattr(form, "_veil_shot_on", False):
            close_shot()
            return
        if getattr(form, "_veil_pc_on", False):
            try:
                form._veil_files.back()
            except Exception:
                log(traceback.format_exc())
            return
        try:
            if form.webview.CanGoBack:
                form.webview.GoBack()
        except Exception:
            log(traceback.format_exc())

    def on_pin(sender, args):
        form.TopMost = not form.TopMost
        pin.Text = "Unpin" if form.TopMost else "Pin"

    def on_hide(sender, args):
        form.Hide()

    def on_pc(sender, args):
        hide_shot_menu()
        toggle_pc()

    def on_shot(sender, args):
        menu = form._veil_shot_menu
        show = not menu.Visible
        menu.Visible = show
        if not show:
            return
        from System.Drawing import Point

        origin = form.PointToClient(panel.PointToScreen(Point(shot.Left, shot.Bottom + 4)))
        menu.Location = origin
        menu.BringToFront()

    def on_full(sender, args):
        take_full_shot()

    def on_part(sender, args):
        take_region_shot()

    def on_band(sender, args):
        close_shot()

    def on_navigated(sender, args):
        try:
            source = form.webview.Source
            if source is None:
                return
            uri = str(source.AbsoluteUri)
        except Exception:
            return
        if uri.startswith(("about:", "http://127.", "http://localhost")):
            return
        box.Text = uri

    go.Click += on_go
    home.Click += on_home
    back.Click += on_back
    pin.Click += on_pin
    pc.Click += on_pc
    shot.Click += on_shot
    hide.Click += on_hide
    form._veil_panel = panel
    form._veil_box = box
    form._veil_back = back
    form._veil_go = go
    form._veil_home = home
    form._veil_pin = pin
    form._veil_pc = pc
    form._veil_shot = shot
    form._veil_hide = hide
    form._veil_pc_on = False
    form._veil_shot_on = False
    form._veil_files = None
    form._veil_picker = None
    panel.Resize += layout_bar
    form.webview.NavigationCompleted += on_navigated
    _refs.extend([
        panel, box, back, go, home, pin, pc, shot, hide, font,
        on_enter, on_go, on_home, on_back, on_pin, on_pc, on_shot, on_hide, on_navigated,
        on_full, on_part, on_band,
    ])

    try:
        user32.SendMessageW(as_hwnd(box.Handle), EM_SETCUEBANNER, 1, "Site, search, or folder path")
    except Exception:
        log(traceback.format_exc())

    tip = WinForms.ToolTip()
    tip.SetToolTip(hide, _chosen_hotkey + " shows it again")
    tip.SetToolTip(pc, "Browse this PC in this window")
    tip.SetToolTip(shot, "Full screen or a region, no notification")
    _refs.append(tip)

    menu = WinForms.Panel()
    menu.Visible = False
    menu.Size = Size(168, 76)
    menu.BackColor = Color.FromArgb(255, 28, 30, 36)
    full = WinForms.Button()
    part = WinForms.Button()
    paint_button(full, "Full screen")
    paint_button(part, "Region")
    full.SetBounds(6, 6, 156, 30)
    part.SetBounds(6, 40, 156, 30)
    full.Click += on_full
    part.Click += on_part
    menu.Controls.Add(full)
    menu.Controls.Add(part)
    form.Controls.Add(menu)
    form._veil_shot_menu = menu

    shots = WinForms.Panel()
    shots.Dock = WinForms.DockStyle.Fill
    shots.Visible = False
    shots.BackColor = Color.FromArgb(255, 20, 21, 26)
    header = WinForms.Panel()
    header.Height = 36
    header.Dock = WinForms.DockStyle.Top
    header.BackColor = shots.BackColor
    band = WinForms.Button()
    paint_button(band, "Close")
    band.Dock = WinForms.DockStyle.Right
    band.Width = 72
    band.Click += on_band
    caption = WinForms.Label()
    caption.Dock = WinForms.DockStyle.Fill
    caption.ForeColor = Color.FromArgb(255, 224, 177, 90)
    caption.BackColor = shots.BackColor
    caption.Font = font
    caption.TextAlign = ContentAlignment.MiddleLeft
    caption.Padding = WinForms.Padding(10, 0, 0, 0)
    picture = WinForms.PictureBox()
    picture.Dock = WinForms.DockStyle.Fill
    picture.SizeMode = WinForms.PictureBoxSizeMode.Zoom
    picture.BackColor = shots.BackColor
    header.Controls.Add(caption)
    header.Controls.Add(band)
    shots.Controls.Add(picture)
    shots.Controls.Add(header)
    form.Controls.Add(shots)
    form._veil_shot_panel = shots
    form._veil_shot_image = picture
    form._veil_shot_label = caption
    _refs.extend([menu, full, part, shots, header, band, caption, picture])

    files = WinForms.Panel()
    files.Dock = WinForms.DockStyle.Fill
    files.Visible = False
    files.BackColor = Color.White
    form.Controls.Add(files)
    form._veil_files_panel = files
    if not _test:
        from veil_files import PcView

        form._veil_files = PcView(_on_place, log)

        def on_files_resize(sender, args):
            if form._veil_pc_on and form._veil_files is not None:
                form._veil_files.sync(files)

        files.Resize += on_files_resize
        _refs.append(on_files_resize)
    _refs.append(files)

    def on_closed(sender, args):
        cancel_region()
        picker = form._veil_picker
        if picker is not None:
            picker.close()
        view = form._veil_files
        if view is not None:
            view.close()

    form.FormClosed += on_closed
    _refs.append(on_closed)

    if _test:
        swatch = WinForms.Panel()
        swatch.BackColor = Color.FromArgb(255, 255, 43, 214)
        swatch.Dock = WinForms.DockStyle.Fill
        form.Controls.Add(swatch)
        swatch.BringToFront()
        panel.BringToFront()
        _refs.append(swatch)

    def on_resize_end(sender, args):
        save_window_bounds(form)

    form.ResizeEnd += on_resize_end
    _refs.append(on_resize_end)
    layout_bar()
    form.TopMost = True
    shield_all(force_tab=True)

    ticks = {"n": 0}

    def on_tick(sender, args):
        ticks["n"] += 1
        try:
            shield_all(force_tab=ticks["n"] <= 10)
            write_ready()
        except Exception:
            log(traceback.format_exc())

    timer = WinForms.Timer()
    timer.Interval = 700
    timer.Tick += on_tick
    timer.Start()
    _refs.append(timer)
    write_ready()
    log("window armed")


def toggle():
    form = _form
    if form is None or not form.IsHandleCreated:
        return
    if form.Visible:
        cancel_region()
        hide_shot_menu()
        form.Hide()
        return
    import System.Windows.Forms as WinForms

    form.Show()
    form.WindowState = WinForms.FormWindowState.Normal
    form.TopMost = True
    form.Activate()
    try:
        shield_all(force_tab=True)
    except Exception:
        log(traceback.format_exc())


def hotkey_loop():
    global _chosen_hotkey

    combos = (
        (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x56, "Ctrl+Alt+V"),
        (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x56, "Ctrl+Shift+V"),
        (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x20, "Ctrl+Alt+Space"),
    )
    registered = False
    for mods, vk, label in combos:
        if user32.RegisterHotKey(None, 1, mods, vk):
            _chosen_hotkey = label
            registered = True
            log("hotkey " + label)
            break
    if not registered:
        log("hotkey registration failed")
    hotkey_ready.set()
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
        if message.message == WM_HOTKEY:
            form = _form
            if form is not None and form.IsHandleCreated:
                try:
                    from System import Action

                    form.BeginInvoke(Action(toggle))
                except Exception:
                    log(traceback.format_exc())
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


hotkey_ready = threading.Event()


def on_shown():
    global _form
    from System import Action

    _form = _window.native
    try:
        _form.BeginInvoke(Action(arm))
    except Exception:
        log(traceback.format_exc())


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def work_area():
    rect = _RECT()
    try:
        user32.SystemParametersInfoW.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            wintypes.UINT,
        ]
        user32.SystemParametersInfoW.restype = wintypes.BOOL
        if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        log(traceback.format_exc())
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def read_saved_window():
    try:
        mode, x, y, width, height = (APP / "window.txt").read_text(encoding="utf-8").split()
        return mode, int(float(x)), int(float(y)), int(float(width)), int(float(height))
    except Exception:
        return None


def save_window_bounds(form):
    if _test:
        return
    try:
        state = int(form.WindowState)
        if state == 1:
            return
        scale = _ui_scale(form)
        rect = form.RestoreBounds if state == 2 else form.Bounds
        (APP / "window.txt").write_text(
            "%s %d %d %d %d\n"
            % (
                "max" if state == 2 else "normal",
                int(rect.X / scale),
                int(rect.Y / scale),
                int(rect.Width / scale),
                int(rect.Height / scale),
            ),
            encoding="utf-8",
        )
    except Exception:
        log(traceback.format_exc())


def place_window():
    if _test:
        return 80, 48, 640, 420, False
    left, top, right, bottom = work_area()
    area_w = max(320, right - left)
    area_h = max(320, bottom - top)
    saved = read_saved_window()
    if saved:
        mode, x, y, width, height = saved
        width = min(max(320, width), area_w)
        height = min(max(360, height), area_h)
        x = min(max(left, x), left + area_w - width)
        y = min(max(top, y), top + area_h - height)
        return x, y, width, height, mode == "max"
    width = min(520, max(360, int(area_w * 0.36)))
    height = min(max(420, int(area_h * 0.86)), area_h - 8)
    x = left + max(0, area_w - width - 12)
    y = top + min(12, max(0, area_h - height))
    return x, y, width, height, False


def main():
    global _window, _page_html
    hide_console()
    claim_single_instance()
    log("--- start pid %s test %s ---" % (os.getpid(), _test))
    APP.mkdir(parents=True, exist_ok=True)
    (APP / "webview").mkdir(parents=True, exist_ok=True)

    threading.Thread(target=hotkey_loop, name="veil-hotkey", daemon=True).start()
    hotkey_ready.wait(2)
    _page_html = HOME_HTML.replace("__HOTKEY__", _chosen_hotkey)

    import webview

    x, y, width, height, maximized = place_window()
    _window = webview.create_window(
        WINDOW_TITLE,
        html=_page_html,
        js_api=Api(),
        width=width,
        height=height,
        x=x,
        y=y,
        resizable=True,
        maximized=maximized,
        on_top=True,
        background_color="#14161c",
        text_select=True,
        zoomable=True,
        min_size=(320, 360),
    )
    _window.events.shown += on_shown
    webview.start(
        gui="edgechromium",
        private_mode=False,
        storage_path=str(APP / "webview"),
    )


if __name__ == "__main__":
    def _hook(exc_type, exc, tb):
        log("".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _thread_hook(args):
            _hook(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_hook
    main()
