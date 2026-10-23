# -*- coding: utf-8 -*-
"""Veil: a private window. Screen-capture APIs skip it, and it has no taskbar button.

Run with pythonw.exe (the desktop shortcut does this). Ctrl+Alt+V hides and shows it.
PC opens This PC inside the same window.
Shot takes a silent full-screen or region screenshot.
If ChatGPT or Gemini is open in this window, the shot is pasted into its message box.
The bar switches the window between dark and light.
The title bar moves the window directly: no drag ghost, and no edge-snap zones.
The pointer stays the normal arrow over text, links, and buttons. Windows draws the
pointer on top of a capture, so a changing pointer would still show on a screen share.
Coming here from a full-screen app keeps the taskbar down. Explorer would otherwise
pop it up, and that pop shows on a capture.
Switching between this window and the shared one does not flash the caption buttons.
Close, minimize, and maximize stay the same color both ways.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote

APP = Path(os.environ.get("APPDATA", str(Path.home()))) / "Veil"
NOTES = APP / "notes.txt"
THEME_FILE = APP / "theme.txt"
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
WM_ACTIVATE = 0x0006
WM_NCACTIVATE = 0x0086
WM_MOUSEACTIVATE = 0x0021
WM_SETREDRAW = 0x000B
WA_INACTIVE = 0
WM_SETCURSOR = 0x0020
DWMWA_TRANSITIONS_FORCEDISABLED = 3
SMTO_ABORTIFHUNG = 0x0002
WH_CALLWNDPROC = 4
WH_MOUSE_LL = 14
WH_CALLWNDPROCRET = 12
GA_ROOT = 2
IDC_ARROW = 32512
GWL_WNDPROC = -4
WM_NCDESTROY = 0x0082
WM_CANCELMODE = 0x001F
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCMOUSEMOVE = 0x00A0
WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202
WM_CAPTURECHANGED = 0x0215
WM_ENTERSIZEMOVE = 0x0231
WM_NCHITTEST = 0x0084
WM_SYSCOMMAND = 0x0112
HTCAPTION = 2
SC_MOVE = 0xF010
SM_CYCAPTION = 4
SM_CXDRAG = 68
SM_CYDRAG = 69
VK_LBUTTON = 0x01
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

# Runs in every page, including new documents. Open shadow roots get the same
# rule so a site editor does not ask Windows for an I-beam.
CURSOR_STYLE_JS = """
(function () {
  if (window.__veilArrow) return;
  var root = document.documentElement;
  if (!root) return;
  window.__veilArrow = 1;
  var css = "*,*::before,*::after{cursor:default !important}";
  function paint(node) {
    try {
      if (!node || node.__veilArrowStyle) return;
      var doc = node.nodeType === 9 ? node : (node.ownerDocument || document);
      var style = doc.createElement("style");
      style.textContent = css;
      if (node.nodeType === 9) (node.head || node.documentElement).appendChild(style);
      else node.appendChild(style);
      node.__veilArrowStyle = 1;
    } catch (e) {}
  }
  function consider(node) {
    if (!node || node.nodeType !== 1 || !node.shadowRoot) return;
    paint(node.shadowRoot);
    watch(node.shadowRoot);
    var list = node.shadowRoot.querySelectorAll("*");
    for (var i = 0; i < list.length; i++) consider(list[i]);
  }
  function watch(node) {
    if (!node || node.__veilArrowWatch || !window.MutationObserver) return;
    node.__veilArrowWatch = 1;
    try {
      var target = node.nodeType === 9 ? node.documentElement : node;
      if (!target) return;
      new MutationObserver(function (records) {
        for (var r = 0; r < records.length; r++) {
          var added = records[r].addedNodes;
          for (var i = 0; i < added.length; i++) consider(added[i]);
        }
      }).observe(target, {childList: true, subtree: true});
    } catch (e) {}
  }
  function scan(start) {
    consider(start);
    if (!start.querySelectorAll) return;
    var all = start.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) consider(all[i]);
  }
  paint(document);
  watch(document);
  scan(root);
  setTimeout(function () { scan(root); }, 400);
  setTimeout(function () { scan(root); }, 1600);
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


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


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
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCapture.argtypes = [wintypes.HWND]
    user32.SetCapture.restype = wintypes.HWND
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.GetCapture.restype = wintypes.HWND
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = wintypes.SHORT
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.CallWindowProcW.argtypes = [
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
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

THEMES = {
    "dark": {
        "bg": (20, 21, 26),
        "field": (16, 17, 22),
        "ink": (236, 231, 220),
        "button": (36, 34, 30),
        "brass": (224, 177, 90),
        "menu": (28, 30, 36),
        "web": "#14161c",
    },
    "light": {
        "bg": (244, 241, 234),
        "field": (255, 255, 255),
        "ink": (28, 27, 24),
        "button": (232, 226, 214),
        "brass": (138, 90, 18),
        "menu": (255, 252, 247),
        "web": "#f4f1ea",
    },
}


def _read_theme():
    try:
        name = THEME_FILE.read_text(encoding="utf-8").strip().lower()
    except Exception:
        name = "dark"
    return "light" if name == "light" else "dark"


_theme = _read_theme()


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
<html lang="en" data-theme="__THEME__">
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
    --kbd: #2a2e38;
    --kbd-line: #3c4250;
    --mark-ink: #1c1b18;
  }
  :root[data-theme="light"] {
    --bg: #f4f1ea;
    --card: #ffffff;
    --ink: #1c1b18;
    --muted: #5e5a52;
    --line: #ddd6c8;
    --brass: #8a5a12;
    --ok: #1d6b45;
    --kbd: #efe8da;
    --kbd-line: #ddd4c4;
    --mark-ink: #fffaf4;
  }
  * { box-sizing: border-box; cursor: default !important; }
  *::before, *::after { cursor: default !important; }
  html, body { height: 100%; margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", sans-serif; }
  .wrap {
    height: 100%; display: flex; flex-direction: column; overflow: auto;
    padding: clamp(12px, 3vw, 22px); gap: clamp(8px, 2vw, 12px);
  }
  .kicker { color: var(--brass); letter-spacing: .14em; font-size: clamp(10px, 2vw, 11px); }
  h1 { font-size: clamp(18px, 4.4vw, 28px); font-weight: 600; margin: 2px 0 0; letter-spacing: -0.03em; }
  .status { color: var(--ok); font-size: clamp(12.5px, 2.5vw, 14px); line-height: 1.45; margin-top: 8px; }
  .hint { color: var(--muted); font-size: clamp(12px, 2.4vw, 13.5px); line-height: 1.5; margin: 8px 0 0; }
  kbd { font-family: Consolas, monospace; background: var(--kbd); border: 1px solid var(--kbd-line); border-radius: 4px; padding: 1px 6px; color: var(--ink); }
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
    border-radius: 999px; padding: 7px 12px; font: 600 13px "Segoe UI", sans-serif; cursor: default;
  }
  button.link:hover { border-color: var(--brass); color: var(--brass); }
  button.link:focus-visible { outline: 1px solid var(--brass); outline-offset: 2px; }
  .credit {
    display: flex; align-items: center; gap: 10px; flex: 0 0 auto;
    color: var(--muted); font-size: 12.5px; line-height: 1.3;
  }
  .mark {
    flex: 0 0 auto; width: 32px; height: 32px; border-radius: 9px;
    display: inline-flex; align-items: center; justify-content: center;
    background: var(--brass); color: var(--mark-ink);
    font-weight: 700; font-size: 12px; letter-spacing: 0.04em;
  }
  @media (max-width: 380px) {
    .credit { font-size: 12px; }
    .mark { width: 28px; height: 28px; }
  }
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
    <footer class="credit">
      <span class="mark" aria-hidden="true">AA</span>
      <span>Created by Abdul Ahad</span>
    </footer>
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
    theme_w = px(58)
    hide_w = px(58)
    url_min = px(128)
    one_row = (
        pad * 2 + back_w + go_w + home_w + pc_w + shot_w + pin_w + theme_w + hide_w
        + gap * 8 + url_min
    )
    two_rows = width < one_row
    row2_need = pad * 2 + home_w + pc_w + shot_w + pin_w + theme_w + hide_w + gap * 5
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
        theme = form._veil_theme
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
                theme_x = hide_x - gap - theme_w
                theme.SetBounds(theme_x, second, theme_w, row_h)
                pin_x = theme_x - gap - pin_w
                pin.SetBounds(pin_x, second, pin_w, row_h)
                home.SetBounds(pin_x - gap - home_w, second, home_w, row_h)
                third = second + row_h + gap
                shot.SetBounds(width - pad - shot_w, third, shot_w, row_h)
                pc.SetBounds(width - pad - shot_w - gap - pc_w, third, pc_w, row_h)
            else:
                hide_x = width - pad - hide_w
                hide.SetBounds(hide_x, second, hide_w, row_h)
                theme_x = hide_x - gap - theme_w
                theme.SetBounds(theme_x, second, theme_w, row_h)
                pin_x = theme_x - gap - pin_w
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
                (theme, theme_w),
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


def _color(name):
    from System.Drawing import Color

    red, green, blue = THEMES[_theme][name]
    return Color.FromArgb(255, red, green, blue)


def _save_theme():
    try:
        APP.mkdir(parents=True, exist_ok=True)
        THEME_FILE.write_text(_theme, encoding="utf-8")
    except Exception:
        log(traceback.format_exc())


def _render_home():
    global _page_html
    _page_html = (
        HOME_HTML.replace("__HOTKEY__", _chosen_hotkey).replace("__THEME__", _theme)
    )


# Resize borders keep the size pointer. Everything inside the window stays an arrow.
_RESIZE_HITS = frozenset({4, 10, 11, 12, 13, 14, 15, 16, 17, 18})
_CURSOR_HOOK = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p
)


class _CWPRETSTRUCT(ctypes.Structure):
    _fields_ = [
        ("lResult", ctypes.c_ssize_t),
        ("lParam", ctypes.c_ssize_t),
        ("wParam", ctypes.c_ssize_t),
        ("message", wintypes.UINT),
        ("hwnd", wintypes.HWND),
    ]


_MSG_AT = _CWPRETSTRUCT.message.offset
_HWND_AT = _CWPRETSTRUCT.hwnd.offset
_LPARAM_AT = _CWPRETSTRUCT.lParam.offset
_CURSOR_MESSAGES = frozenset((WM_SETCURSOR, WM_MOUSEMOVE, WM_NCMOUSEMOVE))


_arrow_handle = None
_cursor_hook = None
_cursor_cb = None
_cursor_top = 0
_cursor_bound = False


def _should_force_arrow(message, is_top, is_ours, hit):
    if not is_ours:
        return False
    if message in (WM_MOUSEMOVE, WM_NCMOUSEMOVE):
        return not is_top
    if message != WM_SETCURSOR:
        return False
    if is_top and hit in _RESIZE_HITS:
        return False
    return True


def _bind_cursor_apis():
    global _cursor_bound, _arrow_handle
    if _cursor_bound:
        return
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [_POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(_POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _CURSOR_HOOK, wintypes.HINSTANCE, wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.CallNextHookEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p,
    ]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _arrow_handle = user32.LoadCursorW(None, IDC_ARROW)
    _cursor_bound = True


def _pin_control_cursors(control):
    import System.Windows.Forms as WinForms

    arrow = WinForms.Cursors.Arrow
    try:
        control.Cursor = arrow
    except Exception:
        pass
    try:
        children = list(control.Controls)
    except Exception:
        return
    for child in children:
        _pin_control_cursors(child)


def _ensure_page_cursor(form=None, force=False):
    form = _form if form is None else form
    if form is None:
        return
    try:
        core = form.webview.CoreWebView2
    except Exception:
        return
    if core is None:
        return
    if not getattr(form, "_veil_cursor_script", False):
        try:
            task = core.AddScriptToExecuteOnDocumentCreatedAsync(CURSOR_STYLE_JS)
            form._veil_cursor_script = True
            form._veil_cursor_task = task
            _refs.append(task)
        except Exception:
            if not getattr(form, "_veil_cursor_logged", False):
                form._veil_cursor_logged = True
                log(traceback.format_exc())
    if force or not getattr(form, "_veil_cursor_now", False):
        try:
            core.ExecuteScriptAsync(CURSOR_STYLE_JS)
            form._veil_cursor_now = True
        except Exception:
            if not getattr(form, "_veil_cursor_logged", False):
                form._veil_cursor_logged = True
                log(traceback.format_exc())


def _ours(hwnd):
    top = _cursor_top
    if not top or not hwnd:
        return False, False
    hwnd_i = as_hwnd(hwnd)
    if hwnd_i == top:
        return True, True
    try:
        root = as_hwnd(user32.GetAncestor(hwnd, GA_ROOT))
    except Exception:
        return False, False
    return root == top, False


def _cursor_proc(nCode, wParam, lParam):
    hook = _cursor_hook
    result = user32.CallNextHookEx(hook, nCode, wParam, lParam) if hook else 0
    if nCode < 0 or not lParam or not _arrow_handle or not _cursor_top:
        return result
    try:
        message = ctypes.c_uint.from_address(lParam + _MSG_AT).value
        if message not in _CURSOR_MESSAGES:
            return result
        hwnd = ctypes.c_void_p.from_address(lParam + _HWND_AT).value or 0
        is_ours, is_top = _ours(hwnd)
        if not is_ours:
            return result
        hit = 0
        if message == WM_SETCURSOR:
            hit = ctypes.c_ssize_t.from_address(lParam + _LPARAM_AT).value & 0xFFFF
        if _should_force_arrow(message, is_top, True, hit):
            user32.SetCursor(_arrow_handle)
    except Exception:
        if not getattr(_cursor_proc, "logged", False):
            _cursor_proc.logged = True
            log(traceback.format_exc())
        return result
    return result


def _nudge_arrow():
    if not _arrow_handle or not _cursor_top:
        return
    try:
        point = _POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return
        hwnd = user32.WindowFromPoint(point)
        is_ours, _is_top = _ours(hwnd)
        if not is_ours:
            return
        client = _POINT(point.x, point.y)
        if not user32.ScreenToClient(_cursor_top, ctypes.byref(client)):
            return
        rect = _RECT()
        if not user32.GetClientRect(_cursor_top, ctypes.byref(rect)):
            return
        width = int(rect.right) - int(rect.left)
        height = int(rect.bottom) - int(rect.top)
        if client.x < 0 or client.y < 0 or client.x >= width or client.y >= height:
            return
        user32.SetCursor(_arrow_handle)
    except Exception:
        return


def _remove_cursor_hook():
    global _cursor_hook, _cursor_top
    hook = _cursor_hook
    _cursor_hook = None
    _cursor_top = 0
    if not hook:
        return
    try:
        user32.UnhookWindowsHookEx(hook)
    except Exception:
        log(traceback.format_exc())


def _ensure_cursor_hook():
    global _cursor_cb, _cursor_hook, _cursor_top
    form = _form
    if form is not None and form.IsHandleCreated:
        _cursor_top = as_hwnd(form.Handle)
    _bind_cursor_apis()
    if not _arrow_handle:
        if not getattr(_ensure_cursor_hook, "logged", False):
            _ensure_cursor_hook.logged = True
            log("arrow cursor missing")
        return
    if _cursor_hook:
        return
    if _cursor_cb is None:
        _cursor_cb = _CURSOR_HOOK(_cursor_proc)
        _refs.append(_cursor_cb)
    hook = user32.SetWindowsHookExW(
        WH_CALLWNDPROCRET,
        _cursor_cb,
        None,
        kernel32.GetCurrentThreadId(),
    )
    if not hook:
        log("cursor hook failed err=%s" % ctypes.get_last_error())
        return
    _cursor_hook = hook
    log("cursor lock on")


def _ensure_cursor_timer(form):
    if form is None or getattr(form, "_veil_cursor_timer", None) is not None:
        return
    import System.Windows.Forms as WinForms

    timer = WinForms.Timer()
    timer.Interval = 32

    def on_cursor(_sender, _args):
        _nudge_arrow()
        _sync_taskbar()
        _sync_caption()

    timer.Tick += on_cursor
    form._veil_cursor_timer = timer
    form._veil_cursor_tick = on_cursor
    _refs.append(timer)
    _refs.append(on_cursor)
    timer.Start()


def hold_arrow(form=None):
    form = _form if form is None else form
    if form is None:
        return
    if not getattr(form, "_veil_cursors_pinned", False):
        try:
            _pin_control_cursors(form)
            form._veil_cursors_pinned = True
        except Exception:
            log(traceback.format_exc())
    _ensure_page_cursor(form)
    _ensure_cursor_hook()
    _ensure_cursor_timer(form)


def paint_button(button, label=None):
    import System.Windows.Forms as WinForms

    if label is not None:
        button.Text = label
    button.FlatStyle = WinForms.FlatStyle.Flat
    button.FlatAppearance.BorderSize = 0
    button.BackColor = _color("button")
    button.ForeColor = _color("ink")
    button.Cursor = WinForms.Cursors.Arrow
    button.TabStop = False
    button.Font = _form._veil_font
    return button


_place_actions = []


def paint_pc(on):
    form = _form
    if form is None:
        return
    button = form._veil_pc
    if on:
        button.BackColor = _color("brass")
        button.ForeColor = _color("bg")
    else:
        button.BackColor = _color("button")
        button.ForeColor = _color("ink")
    form._veil_pc_on = on


def _apply_chrome():
    form = _form
    if form is None:
        return
    ink = _color("ink")
    bg = _color("bg")
    form.BackColor = bg
    panel = getattr(form, "_veil_panel", None)
    if panel is not None:
        panel.BackColor = bg
    box = getattr(form, "_veil_box", None)
    if box is not None:
        box.BackColor = _color("field")
        box.ForeColor = ink
    for name in (
        "_veil_back", "_veil_go", "_veil_home", "_veil_pin", "_veil_shot",
        "_veil_theme", "_veil_hide",
    ):
        button = getattr(form, name, None)
        if button is not None:
            paint_button(button)
    paint_pc(getattr(form, "_veil_pc_on", False))
    menu = getattr(form, "_veil_shot_menu", None)
    if menu is not None:
        menu.BackColor = _color("menu")
        for button in menu.Controls:
            paint_button(button)
    shots = getattr(form, "_veil_shot_panel", None)
    if shots is not None:
        shots.BackColor = bg
        picture = form._veil_shot_image
        picture.BackColor = bg
        label = form._veil_shot_label
        label.BackColor = bg
        label.ForeColor = _color("brass")
        header = label.Parent
        if header is not None:
            header.BackColor = bg
            import System.Windows.Forms as WinForms
            for control in header.Controls:
                if isinstance(control, WinForms.Button):
                    paint_button(control)
    _pin_control_cursors(form)


def _apply_home_theme():
    form = _form
    if form is None:
        return
    try:
        core = form.webview.CoreWebView2
        if core is not None:
            core.ExecuteScriptAsync(
                "document.documentElement.dataset.theme = '%s';" % _theme
            )
    except Exception:
        log(traceback.format_exc())


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


class _MoveDrag:
    def __init__(self):
        self.pending = False
        self.active = False
        self.was_max = False
        self.x0 = 0
        self.y0 = 0
        self.left = 0
        self.top = 0


_move_hooks = {}
_move_forms = {}
_drags = {}
_move_cb = None
_rect_bound = False
_send_message = None
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


def _signed_ptr(value):
    value = int(value) & ((1 << 64) - 1)
    if value >= (1 << 63):
        value -= 1 << 64
    return value


def _hook_addr(callback):
    return _signed_ptr(ctypes.cast(callback, ctypes.c_void_p).value or 0)


def _current_proc(hwnd):
    return _signed_ptr(user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC))


def _cursor():
    point = _POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return 0, 0
    return int(point.x), int(point.y)


def _window_rect(hwnd):
    global _rect_bound
    if not _rect_bound:
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        _rect_bound = True
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0, 0, 0, 0
    return (
        int(rect.left),
        int(rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


def _plain_offset(anchor, origin, cursor):
    return anchor[0] + (cursor[0] - origin[0]), anchor[1] + (cursor[1] - origin[1])


def _past_drag_threshold(origin, cursor):
    span_x = user32.GetSystemMetrics(SM_CXDRAG)
    span_y = user32.GetSystemMetrics(SM_CYDRAG)
    if span_x < 1:
        span_x = 4
    if span_y < 1:
        span_y = 4
    return abs(cursor[0] - origin[0]) >= span_x or abs(cursor[1] - origin[1]) >= span_y


def _button_down():
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def _send(hwnd, msg, wparam, lparam):
    global _send_message
    if _send_message is None:
        proto = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        _send_message = proto(("SendMessageW", user32))
    return int(_send_message(hwnd, msg, wparam, lparam))


def _hit_at_cursor(hwnd):
    x, y = _cursor()
    packed = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
    return int(_send(hwnd, WM_NCHITTEST, 0, packed))


def _captured(hwnd):
    got = user32.GetCapture()
    if not got:
        return False
    return as_hwnd(got) == as_hwnd(hwnd)


def _is_zoomed(form):
    try:
        return int(form.WindowState) == 2
    except Exception:
        return False


def _toggle_zoom(form):
    import System.Windows.Forms as WinForms

    form.WindowState = (
        WinForms.FormWindowState.Normal
        if _is_zoomed(form)
        else WinForms.FormWindowState.Maximized
    )
    save_window_bounds(form)


def _restore_for_move(form, hwnd, cursor):
    import System.Windows.Forms as WinForms

    left, _top, width, _height = _window_rect(hwnd)
    ratio = (cursor[0] - left) / width if width else 0.5
    if ratio < 0:
        ratio = 0.0
    elif ratio > 1:
        ratio = 1.0
    bounds = form.RestoreBounds
    new_w = int(bounds.Width)
    new_h = int(bounds.Height)
    if new_w < 320:
        new_w = 320
    if new_h < 360:
        new_h = 360
    caption = user32.GetSystemMetrics(SM_CYCAPTION)
    if caption <= 0:
        caption = 28
    new_left = int(cursor[0] - new_w * ratio)
    new_top = int(cursor[1] - caption // 2)
    form.WindowState = WinForms.FormWindowState.Normal
    user32.SetWindowPos(hwnd, None, new_left, new_top, new_w, new_h, SWP_NOZORDER)
    return new_left, new_top


def _ensure_drag_timer(form):
    if getattr(form, "_veil_drag_timer", None) is not None:
        return
    import System.Windows.Forms as WinForms

    timer = WinForms.Timer()
    timer.Interval = 16

    def on_drag_tick(_sender, _args):
        try:
            _drag_tick(form)
        except Exception:
            log(traceback.format_exc())

    timer.Tick += on_drag_tick
    form._veil_drag_timer = timer
    form._veil_drag_tick = on_drag_tick
    _refs.append(timer)
    _refs.append(on_drag_tick)


def _stop_drag_timer(form):
    timer = None if form is None else getattr(form, "_veil_drag_timer", None)
    if timer is not None:
        try:
            timer.Stop()
        except Exception:
            log(traceback.format_exc())


def _end_plain_move(hwnd, save):
    hwnd = as_hwnd(hwnd)
    drag = _drags.get(hwnd)
    if drag is None or not (drag.pending or drag.active):
        return
    moved = drag.active
    drag.pending = False
    drag.active = False
    drag.was_max = False
    form = _move_forms.get(hwnd)
    _stop_drag_timer(form)
    if _captured(hwnd):
        user32.ReleaseCapture()
    if save and moved and form is not None:
        save_window_bounds(form)


def _start_plain_move(hwnd):
    hwnd = as_hwnd(hwnd)
    form = _move_forms.get(hwnd)
    if form is None:
        return
    try:
        if form.Visible:
            form.Activate()
    except Exception:
        log(traceback.format_exc())
    cursor = _cursor()
    left, top, _width, _height = _window_rect(hwnd)
    drag = _drags.get(hwnd)
    if drag is None:
        drag = _MoveDrag()
        _drags[hwnd] = drag
    drag.pending = True
    drag.active = False
    drag.was_max = _is_zoomed(form)
    drag.x0, drag.y0 = cursor
    drag.left, drag.top = left, top
    user32.SetCapture(hwnd)
    _ensure_drag_timer(form)
    form._veil_drag_timer.Start()


def _drag_tick(form):
    if form is None or not form.IsHandleCreated:
        return
    hwnd = as_hwnd(form.Handle)
    drag = _drags.get(hwnd)
    if drag is None or not (drag.pending or drag.active):
        _stop_drag_timer(form)
        return
    if not _button_down():
        _end_plain_move(hwnd, save=True)
        return
    cursor = _cursor()
    if drag.pending:
        if not _past_drag_threshold((drag.x0, drag.y0), cursor):
            return
        if drag.was_max:
            drag.left, drag.top = _restore_for_move(form, hwnd, cursor)
            drag.x0, drag.y0 = _cursor()
            drag.was_max = False
        drag.pending = False
        drag.active = True
    x, y = _plain_offset((drag.left, drag.top), (drag.x0, drag.y0), cursor)
    user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, SWP_NOSIZE | SWP_NOZORDER)


def _release_move_if_let_go(form):
    if form is None or not form.IsHandleCreated:
        return
    hwnd = as_hwnd(form.Handle)
    drag = _drags.get(hwnd)
    if drag is None or not (drag.pending or drag.active):
        return
    if _button_down():
        _drag_tick(form)
        return
    _end_plain_move(hwnd, save=True)


_send_timeout_fn = None
_dwm = None
_caption_held = 0
_caption_painted = 0
_caption_release_at = 0.0
_caption_ping_at = 0.0
_caption_muted = set()
_caption_lock = 0
_redraw_frozen = 0
_redraw_since = 0.0
_caption_guard_at = 0.0
_caption_in_activate = False
_caption_hold_depth = 0
_lock_bound = False
_caption_busy = False
_caption_call_hook = None
_caption_call_cb = None
_caption_mouse_hook = None
_caption_mouse_cb = None


class _CWPSTRUCT(ctypes.Structure):
    _fields_ = [
        ("lParam", ctypes.c_ssize_t),
        ("wParam", ctypes.c_ssize_t),
        ("message", wintypes.UINT),
        ("hwnd", wintypes.HWND),
    ]


_CWP_MSG = _CWPSTRUCT.message.offset
_CWP_HWND = _CWPSTRUCT.hwnd.offset
_CAPTION_CLICKS = frozenset((0x0201, 0x0204, 0x0207, 0x020B))


def _send_timeout(hwnd, msg, wparam, lparam, wait_ms=80):
    global _send_timeout_fn
    if _send_timeout_fn is None:
        proto = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_ssize_t),
        )
        _send_timeout_fn = proto(("SendMessageTimeoutW", user32))
    result = ctypes.c_ssize_t()
    if not _send_timeout_fn(
        hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, wait_ms, ctypes.byref(result)
    ):
        return None
    return int(result.value)


def _set_transitions(hwnd, disabled):
    """Stop the caption-button fade. The attribute is per window, so it is put back."""
    global _dwm
    if _dwm is None:
        try:
            _dwm = ctypes.WinDLL("dwmapi")
            _dwm.DwmSetWindowAttribute.argtypes = [
                wintypes.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
            ]
            _dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        except Exception:
            _dwm = False
    if _dwm is False or not hwnd:
        return False
    flag = ctypes.c_int(1 if disabled else 0)
    hr = _dwm.DwmSetWindowAttribute(
        hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(flag), ctypes.sizeof(flag)
    )
    hwnd = as_hwnd(hwnd)
    if disabled and hr == 0 and not _veil_hwnd(hwnd):
        _caption_muted.add(hwnd)
    elif not disabled:
        _caption_muted.discard(hwnd)
    return hr == 0


def _caption_target(hwnd):
    if not hwnd:
        return 0
    try:
        _bind_taskbar()
    except Exception:
        return 0
    hwnd = as_hwnd(hwnd)
    if not hwnd or not user32.IsWindow(hwnd) or _veil_hwnd(hwnd):
        return 0
    try:
        root = user32.GetAncestor(hwnd, GA_ROOT)
        if root:
            hwnd = as_hwnd(root)
    except Exception:
        pass
    if not hwnd or _veil_hwnd(hwnd):
        return 0
    if class_name(hwnd) in (
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
    ):
        return 0
    try:
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            return 0
    except Exception:
        return 0
    return hwnd


def _arm_guard():
    global _caption_guard_at
    if not _caption_guard_at:
        _caption_guard_at = time.monotonic()


def _clear_guard():
    global _caption_guard_at
    if not _redraw_frozen and not _caption_lock:
        _caption_guard_at = 0.0


def _hold_caption(hwnd, repaint, wait_ms=80):
    """Keep Close / Minimize / Maximize on the active color. -1 does not repaint."""
    global _caption_held, _caption_painted, _caption_release_at, _caption_ping_at
    if _test:
        return
    hwnd = _caption_target(hwnd)
    if not hwnd:
        return
    try:
        _set_transitions(hwnd, True)
        sent = _send_timeout(hwnd, WM_NCACTIVATE, 1, 0 if repaint else -1, wait_ms)
    except Exception:
        log(traceback.format_exc())
        return
    if sent is None:
        return
    _caption_held = hwnd
    _caption_release_at = 0.0
    _caption_ping_at = time.monotonic()
    if repaint:
        _caption_painted = hwnd
        if not getattr(_hold_caption, "logged", False):
            _hold_caption.logged = True
            log("caption held")


def _freeze_redraw(hwnd):
    global _redraw_frozen, _redraw_since
    if not hwnd or _redraw_frozen or _test:
        return False
    try:
        if _send_timeout(hwnd, WM_SETREDRAW, 0, 0, 20) is None:
            return False
    except Exception:
        log(traceback.format_exc())
        return False
    _redraw_frozen = hwnd
    _redraw_since = time.monotonic()
    _arm_guard()
    return True


def _thaw_redraw():
    global _redraw_frozen, _caption_guard_at
    hwnd = _redraw_frozen
    if not hwnd:
        return
    ok = False
    try:
        if not user32.IsWindow(hwnd):
            ok = True
        else:
            ok = _send_timeout(hwnd, WM_SETREDRAW, 1, 0, 20) is not None
    except Exception:
        log(traceback.format_exc())
    if not ok:
        # A hung window must not be poked on every timer tick.
        if time.monotonic() - _redraw_since > 1.0:
            _redraw_frozen = 0
            _clear_guard()
            log("caption redraw restore gave up")
        else:
            _caption_guard_at = time.monotonic()
        return
    _redraw_frozen = 0
    _clear_guard()


def _release_frozen_caption():
    global _caption_held, _caption_painted, _caption_release_at, _caption_ping_at
    _thaw_redraw()
    _unlock_window()
    hwnds = list(_caption_muted)
    held = _caption_held
    _caption_held = 0
    _caption_painted = 0
    _caption_release_at = 0.0
    _caption_ping_at = 0.0
    if held:
        hwnds.append(held)
    seen = set()
    for hwnd in hwnds:
        if not hwnd or hwnd in seen:
            continue
        seen.add(hwnd)
        try:
            if user32.IsWindow(hwnd):
                _set_transitions(hwnd, False)
        except Exception:
            log(traceback.format_exc())
    _caption_muted.clear()


def _lock_window(hwnd):
    global _lock_bound, _caption_lock
    if not hwnd or _caption_lock or _test:
        return False
    try:
        if not _lock_bound:
            user32.LockWindowUpdate.argtypes = [wintypes.HWND]
            user32.LockWindowUpdate.restype = wintypes.BOOL
            _lock_bound = True
        if not user32.LockWindowUpdate(hwnd):
            return False
    except Exception:
        return False
    _caption_lock = hwnd
    _arm_guard()
    return True


def _unlock_window():
    global _caption_lock
    if not _caption_lock:
        return
    try:
        user32.LockWindowUpdate(0)
    except Exception:
        pass
    _caption_lock = 0
    _clear_guard()


def _finish_other_caption(other):
    """Paint the active caption once, after redraw is allowed again."""
    need = bool(_redraw_frozen or _caption_lock)
    frozen = _redraw_frozen
    _thaw_redraw()
    target = _caption_target(other) or _caption_target(frozen)
    if target and (need or _caption_painted != target):
        _hold_caption(target, repaint=True)
    _unlock_window()


def _schedule_caption_release():
    global _caption_release_at
    if not _caption_release_at:
        _caption_release_at = time.monotonic() + 0.35


def _veil_focused():
    form = _form
    try:
        return bool(
            form is not None
            and form.IsHandleCreated
            and form.Visible
            and _veil_hwnd(user32.GetForegroundWindow())
        )
    except Exception:
        return False


def _point_in_veil(x, y):
    form = _form
    try:
        if form is None or not form.IsHandleCreated:
            return False
        left, top, width, height = _window_rect(as_hwnd(form.Handle))
    except Exception:
        return False
    return width > 0 and height > 0 and left <= x < left + width and top <= y < top + height


def _prime_caption(hwnd):
    """Call before Veil takes focus, while the other window still looks active."""
    if _test:
        return
    other = _caption_target(hwnd)
    if not other:
        return
    try:
        _set_transitions(other, True)
    except Exception:
        log(traceback.format_exc())
    _freeze_redraw(other)
    _lock_window(other)


def _sync_caption():
    global _caption_release_at, _caption_held
    if (
        _caption_guard_at
        and not _caption_hold_depth
        and time.monotonic() - _caption_guard_at > 0.1
    ):
        stale = _redraw_frozen or _caption_lock
        _finish_other_caption(stale if _veil_focused() else 0)
    if _test:
        return
    if _veil_focused():
        _caption_release_at = 0.0
        other = _caption_target(_last_other)
        if other and _caption_painted != other:
            _hold_caption(other, repaint=True)
            return
        if _caption_held and not _caption_target(_caption_held):
            _caption_held = 0
            return
        if _caption_held and time.monotonic() - _caption_ping_at >= 0.5:
            _hold_caption(_caption_held, repaint=False, wait_ms=20)
        return
    if not _caption_held and not _caption_muted:
        return
    now = time.monotonic()
    if not _caption_release_at:
        _caption_release_at = now + 0.35
    if now >= _caption_release_at:
        _release_frozen_caption()


def _on_activate_message(hwnd, wparam, lparam):
    global _last_other, _caption_painted, _caption_in_activate
    if _caption_in_activate:
        pair = _move_hooks.get(hwnd)
        if pair:
            return user32.CallWindowProcW(pair[1], hwnd, WM_ACTIVATE, wparam, lparam)
        return 0
    active = (int(wparam) & 0xFFFF) != WA_INACTIVE
    other = _caption_target(lparam) or _caption_target(_last_other)
    if other and not _test:
        try:
            _set_transitions(other, True)
        except Exception:
            log(traceback.format_exc())
    pair = _move_hooks.get(hwnd)
    result = 0
    _caption_in_activate = True
    try:
        if pair:
            result = user32.CallWindowProcW(pair[1], hwnd, WM_ACTIVATE, wparam, lparam)
        if not _test:
            if active:
                _finish_other_caption(other)
            else:
                if other:
                    _last_other = other
                if _redraw_frozen or _caption_lock:
                    _finish_other_caption(0)
                # Next entry has to paint again. The shared window was really activated.
                _caption_painted = 0
                _schedule_caption_release()
    finally:
        _caption_in_activate = False
        _unlock_window()
    return result


def _caption_before_activate(hwnd):
    """Same-thread clicks reach here before the other window is deactivated."""
    if _test or _caption_busy or not hwnd or not _veil_hwnd(hwnd) or _veil_focused():
        return
    other = _caption_target(user32.GetForegroundWindow()) or _caption_target(_last_other)
    if not other:
        return
    try:
        _set_transitions(other, True)
    except Exception:
        return
    _freeze_redraw(other)
    _lock_window(other)


def _caption_call_proc(nCode, wParam, lParam):
    if nCode >= 0 and lParam and not _test:
        try:
            if ctypes.c_uint.from_address(lParam + _CWP_MSG).value == WM_MOUSEACTIVATE:
                hwnd = ctypes.c_void_p.from_address(lParam + _CWP_HWND).value or 0
                _caption_before_activate(hwnd)
        except Exception:
            pass
    hook = _caption_call_hook
    if not hook:
        return 0
    return user32.CallNextHookEx(hook, nCode, wParam, lParam)


def _caption_before_click(x, y):
    """Page clicks land in WebView2, so they never reach our window procedure."""
    global _caption_busy
    if _caption_busy or _test:
        return
    _caption_busy = True
    try:
        form = _form
        if form is None or not form.IsHandleCreated or not form.Visible:
            return
        inside = _point_in_veil(x, y)
        fg = user32.GetForegroundWindow()
        if _veil_hwnd(fg):
            if inside:
                return
            target = _caption_target(user32.WindowFromPoint(_POINT(int(x), int(y))))
            if target:
                _set_transitions(target, True)
            return
        if not inside:
            return
        other = _caption_target(fg) or _caption_target(_last_other)
        if not other:
            return
        _set_transitions(other, True)
        _freeze_redraw(other)
        _lock_window(other)
    except Exception:
        return
    finally:
        _caption_busy = False


def _caption_mouse_proc(nCode, wParam, lParam):
    if nCode >= 0 and lParam and (int(wParam) & 0xFFFFFFFF) in _CAPTION_CLICKS:
        try:
            pt = _POINT.from_address(int(lParam))
            _caption_before_click(int(pt.x), int(pt.y))
        except Exception:
            pass
    hook = _caption_mouse_hook
    if not hook:
        return 0
    return user32.CallNextHookEx(hook, nCode, wParam, lParam)


def _ensure_caption_hooks():
    global _caption_call_hook, _caption_call_cb, _caption_mouse_hook, _caption_mouse_cb
    if _test or (_caption_call_hook and _caption_mouse_hook):
        return
    _bind_cursor_apis()
    try:
        _bind_taskbar()
    except Exception:
        log(traceback.format_exc())
    _set_transitions(0, True)
    if _caption_call_cb is None:
        _caption_call_cb = _CURSOR_HOOK(_caption_call_proc)
        _refs.append(_caption_call_cb)
    if _caption_mouse_cb is None:
        _caption_mouse_cb = _CURSOR_HOOK(_caption_mouse_proc)
        _refs.append(_caption_mouse_cb)
    if not _caption_call_hook:
        hook = user32.SetWindowsHookExW(
            WH_CALLWNDPROC, _caption_call_cb, None, kernel32.GetCurrentThreadId()
        )
        if hook:
            _caption_call_hook = hook
        else:
            log("caption call hook failed err=%s" % ctypes.get_last_error())
    if not _caption_mouse_hook:
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, _caption_mouse_cb, None, 0)
        if hook:
            _caption_mouse_hook = hook
        else:
            log("caption mouse hook failed err=%s" % ctypes.get_last_error())


def _remove_caption_hooks():
    global _caption_call_hook, _caption_mouse_hook
    for name in ("_caption_call_hook", "_caption_mouse_hook"):
        hook = globals().get(name)
        globals()[name] = None
        if not hook:
            continue
        try:
            user32.UnhookWindowsHookEx(hook)
        except Exception:
            log(traceback.format_exc())


def _on_move_message(hwnd, msg, wparam, lparam):
    if msg == WM_NCACTIVATE and (int(wparam) & 0xFFFF) == WA_INACTIVE:
        # Stay on the active caption colors. Otherwise Close and Minimize dim.
        pair = _move_hooks.get(hwnd)
        if not pair:
            return 1
        return user32.CallWindowProcW(pair[1], hwnd, msg, 1, -1)
    if msg == WM_ACTIVATE:
        return _on_activate_message(hwnd, wparam, lparam)
    if msg == WM_NCDESTROY:
        form = _move_forms.pop(hwnd, None)
        _stop_drag_timer(form)
        _drags.pop(hwnd, None)
        pair = _move_hooks.pop(hwnd, None)
        if pair and user32.IsWindow(hwnd):
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, pair[1])
            return user32.CallWindowProcW(pair[1], hwnd, msg, wparam, lparam)
        return 0
    if msg == WM_SYSCOMMAND and (int(wparam) & 0xFFF0) == SC_MOVE:
        return 0
    if msg == WM_ENTERSIZEMOVE:
        try:
            moving = _hit_at_cursor(hwnd) == HTCAPTION
        except Exception:
            log(traceback.format_exc())
            moving = False
        if moving and _button_down():
            user32.ReleaseCapture()
            _start_plain_move(hwnd)
            return 0
        return None
    hit = int(wparam) & 0xFFFF
    if msg == WM_NCLBUTTONDOWN and hit == HTCAPTION:
        _start_plain_move(hwnd)
        return 0
    if msg == WM_NCLBUTTONDBLCLK and hit == HTCAPTION:
        _end_plain_move(hwnd, save=False)
        form = _move_forms.get(hwnd)
        if form is not None:
            _toggle_zoom(form)
        return 0
    if msg in (WM_MOUSEMOVE, WM_NCMOUSEMOVE):
        drag = _drags.get(hwnd)
        if drag is not None and (drag.pending or drag.active):
            form = _move_forms.get(hwnd)
            if form is not None:
                _drag_tick(form)
            return 0
        return None
    if msg in (WM_LBUTTONUP, WM_NCLBUTTONUP):
        drag = _drags.get(hwnd)
        if drag is not None and (drag.pending or drag.active):
            _end_plain_move(hwnd, save=True)
            return 0
        return None
    if msg == WM_CAPTURECHANGED:
        drag = _drags.get(hwnd)
        if drag is not None and (drag.pending or drag.active):
            moved = drag.active
            drag.pending = False
            drag.active = False
            drag.was_max = False
            form = _move_forms.get(hwnd)
            _stop_drag_timer(form)
            if moved and form is not None:
                save_window_bounds(form)
        return None
    if msg == WM_CANCELMODE:
        _end_plain_move(hwnd, save=True)
        return None
    return None


def _move_proc(hwnd, msg, wparam, lparam):
    hwnd_i = as_hwnd(hwnd)
    try:
        result = _on_move_message(hwnd_i, int(msg) & 0xFFFFFFFF, wparam, lparam)
    except Exception:
        log(traceback.format_exc())
        result = None
    if result is not None:
        return result
    pair = _move_hooks.get(hwnd_i)
    if not pair:
        return 0
    return user32.CallWindowProcW(pair[1], hwnd, int(msg) & 0xFFFFFFFF, wparam, lparam)


def _ensure_move_hook(form):
    global _move_cb
    if form is None or not form.IsHandleCreated:
        return
    hwnd = as_hwnd(form.Handle)
    _move_forms[hwnd] = form
    _ensure_drag_timer(form)
    try:
        _ensure_caption_hooks()
    except Exception:
        log(traceback.format_exc())
    if _move_cb is None:
        _move_cb = WNDPROC(_move_proc)
    current = _current_proc(hwnd)
    installed = _hook_addr(_move_cb)
    if current == installed and hwnd in _move_hooks:
        return
    previous = _signed_ptr(user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, installed))
    if previous in (0, installed):
        log("plain move hook failed err=%s" % ctypes.get_last_error())
        return
    _move_hooks[hwnd] = (_move_cb, previous)
    try:
        _set_transitions(hwnd, True)
    except Exception:
        log(traceback.format_exc())


def arm():
    global _form
    import System.Windows.Forms as WinForms
    from System.Drawing import Color, ContentAlignment, Font, Size

    form = _form
    font = Font("Segoe UI", 9.0)
    form._veil_font = font
    form.BackColor = _color("bg")

    panel = WinForms.Panel()
    panel.Height = 48
    panel.Dock = WinForms.DockStyle.Top
    panel.BackColor = _color("bg")
    form.Controls.Add(panel)
    panel.BringToFront()

    box = WinForms.TextBox()
    box.BorderStyle = WinForms.BorderStyle.FixedSingle
    box.BackColor = _color("field")
    box.ForeColor = _color("ink")
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
    theme = WinForms.Button()
    hide = WinForms.Button()
    for button, label in (
        (back, "←"),
        (go, "Go"),
        (home, "Home"),
        (pin, "Unpin"),
        (pc, "PC"),
        (shot, "Shot"),
        (theme, "Dark" if _theme == "light" else "Light"),
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

    def on_theme(sender, args):
        global _theme
        hide_shot_menu()
        _theme = "light" if _theme == "dark" else "dark"
        _save_theme()
        _render_home()
        theme.Text = "Dark" if _theme == "light" else "Light"
        tip.SetToolTip(
            theme,
            "Switch to %s appearance" % ("dark" if _theme == "light" else "light"),
        )
        _apply_chrome()
        _apply_home_theme()

    def on_hide(sender, args):
        form.Hide()
        _sync_taskbar()

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
        _ensure_page_cursor(form, force=True)
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
    theme.Click += on_theme
    hide.Click += on_hide
    form._veil_panel = panel
    form._veil_box = box
    form._veil_back = back
    form._veil_go = go
    form._veil_home = home
    form._veil_pin = pin
    form._veil_pc = pc
    form._veil_shot = shot
    form._veil_theme = theme
    form._veil_hide = hide
    form._veil_pc_on = False
    form._veil_shot_on = False
    form._veil_files = None
    form._veil_picker = None
    panel.Resize += layout_bar
    form.webview.NavigationCompleted += on_navigated
    _refs.extend([
        panel, box, back, go, home, pin, pc, shot, theme, hide, font,
        on_enter, on_go, on_home, on_back, on_pin, on_pc, on_shot, on_theme, on_hide, on_navigated,
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
    tip.SetToolTip(
        theme,
        "Switch to %s appearance" % ("dark" if _theme == "light" else "light"),
    )
    _refs.append(tip)

    menu = WinForms.Panel()
    menu.Visible = False
    menu.Size = Size(168, 76)
    menu.BackColor = _color("menu")
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
    shots.BackColor = _color("bg")
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
    caption.ForeColor = _color("brass")
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
        _release_frozen_caption()
        _remove_caption_hooks()
        _restore_taskbar()
        _remove_cursor_hook()
        cancel_region()
        picker = form._veil_picker
        if picker is not None:
            picker.close()
        view = form._veil_files
        if view is not None:
            view.close()

    form.FormClosed += on_closed
    _refs.append(on_closed)

    def on_activation(_sender, _args):
        _sync_taskbar()

    form.Activated += on_activation
    form.Deactivate += on_activation
    _refs.append(on_activation)

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
    _apply_chrome()
    layout_bar()
    hold_arrow(form)
    form.TopMost = True
    shield_all(force_tab=True)
    _ensure_move_hook(form)

    ticks = {"n": 0}

    def on_tick(sender, args):
        ticks["n"] += 1
        try:
            shield_all(force_tab=ticks["n"] <= 10)
            _ensure_move_hook(form)
            _release_move_if_let_go(form)
            hold_arrow(form)
            _sync_taskbar()
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
    global _caption_hold_depth
    form = _form
    if form is None or not form.IsHandleCreated:
        return
    if form.Visible:
        cancel_region()
        hide_shot_menu()
        other = _caption_target(_caption_held) or _caption_target(_last_other)
        if other:
            try:
                _set_transitions(other, True)
            except Exception:
                log(traceback.format_exc())
        form.Hide()
        _schedule_caption_release()
        _sync_taskbar()
        return
    import System.Windows.Forms as WinForms

    _remember_outside()
    if _cover_fullscreen:
        _hide_taskbars()
    _caption_hold_depth += 1
    try:
        _prime_caption(_last_other)
        form.Show()
        form.WindowState = WinForms.FormWindowState.Normal
        form.TopMost = True
        form.Activate()
    finally:
        _finish_other_caption(_last_other)
        _caption_hold_depth -= 1
    try:
        shield_all(force_tab=True)
    except Exception:
        log(traceback.format_exc())
    _sync_taskbar()


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
        _ensure_cursor_timer(_form)
        _ensure_move_hook(_form)
        _hold_caption(_last_other, repaint=True)
    except Exception:
        log(traceback.format_exc())
    _sync_taskbar()
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


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_last_other = 0
_cover_fullscreen = False
_hidden_taskbars = set()
_taskbar_hidden_by_us = False
_taskbar_bound = False
_taskbar_cache = []
_taskbar_cache_at = 0.0
_SW_SHOWNA = 8


def _covers_monitor(left, top, width, height, mon):
    """True when a window covers a monitor, not merely the work area above the taskbar."""
    if width < 100 or height < 100:
        return False
    ml, mt, mr, mb = mon
    slop = 8
    return (
        left <= ml + slop
        and top <= mt + slop
        and left + width >= mr - slop
        and top + height >= mb - slop
    )


EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
_taskbar_event_cb = None
_taskbar_event_hook = None


def _taskbar_event(_hook, _event, hwnd, id_object, _id_child, _thread, _tick):
    # Only while Veil itself is holding the bar down. A full-screen app in front
    # must keep the normal shell behavior.
    if not _taskbar_hidden_by_us or not _cover_fullscreen or not hwnd:
        return
    if int(id_object) != OBJID_WINDOW:
        return
    try:
        hwnd_i = as_hwnd(hwnd)
        if hwnd_i not in _hidden_taskbars and class_name(hwnd) not in (
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
        ):
            return
        if user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 0)
            _hidden_taskbars.add(hwnd_i)
    except Exception:
        return


def _bind_taskbar():
    global _taskbar_bound, _taskbar_event_cb, _taskbar_event_hook
    if _taskbar_bound:
        return
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWinEventHook.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HMODULE,
        _WINEVENTPROC,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    user32.SetWinEventHook.restype = ctypes.c_void_p
    _taskbar_bound = True
    if _test:
        return
    _taskbar_event_cb = _WINEVENTPROC(_taskbar_event)
    _refs.append(_taskbar_event_cb)
    _taskbar_event_hook = user32.SetWinEventHook(
        EVENT_OBJECT_SHOW,
        EVENT_OBJECT_SHOW,
        None,
        _taskbar_event_cb,
        0,
        0,
        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
    )
    if not _taskbar_event_hook:
        log("taskbar watch failed err=%s" % ctypes.get_last_error())


def _veil_hwnd(hwnd):
    form = _form
    if not hwnd or form is None or not form.IsHandleCreated:
        return False
    try:
        top = as_hwnd(form.Handle)
    except Exception:
        return False
    hwnd_i = as_hwnd(hwnd)
    if hwnd_i == top:
        return True
    try:
        _bind_taskbar()
        return as_hwnd(user32.GetAncestor(hwnd, GA_ROOT)) == top
    except Exception:
        return False


def _monitor_rect(hwnd):
    _bind_taskbar()
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if not monitor:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def _window_is_fullscreen(hwnd):
    if not hwnd or _veil_hwnd(hwnd) or not user32.IsWindow(hwnd):
        return False
    try:
        _bind_taskbar()
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            return False
        if class_name(hwnd) in (
            "Progman",
            "WorkerW",
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
        ):
            return False
        left, top, width, height = _window_rect(hwnd)
        mon = _monitor_rect(hwnd)
        if mon is None:
            return False
        return _covers_monitor(left, top, width, height, mon)
    except Exception:
        return False


def _remember_outside():
    global _last_other, _cover_fullscreen
    fg = user32.GetForegroundWindow()
    if not fg or _veil_hwnd(fg):
        return
    fg = as_hwnd(fg)
    _last_other = fg
    _cover_fullscreen = _window_is_fullscreen(fg)


def _taskbar_hwnds():
    global _taskbar_cache, _taskbar_cache_at
    now = time.monotonic()
    if _taskbar_cache and now - _taskbar_cache_at < 0.5:
        return list(_taskbar_cache)
    found = []
    primary = user32.FindWindowW("Shell_TrayWnd", None)
    if primary:
        found.append(as_hwnd(primary))
    extra = []

    def _cb(hwnd, _lp):
        if class_name(hwnd) == "Shell_SecondaryTrayWnd":
            extra.append(as_hwnd(hwnd))
        return True

    callback = WNDENUMPROC(_cb)
    user32.EnumWindows(callback, 0)
    found.extend(extra)
    _taskbar_cache = found
    _taskbar_cache_at = now
    return list(found)


def _hide_taskbars():
    global _taskbar_hidden_by_us
    if _test or not _cover_fullscreen:
        return
    # Latch before the hide so Explorer's show-event can put the bar straight back down.
    _taskbar_hidden_by_us = True
    hid = False
    for hwnd in _taskbar_hwnds():
        if not user32.IsWindowVisible(hwnd):
            continue
        user32.ShowWindow(hwnd, 0)
        _hidden_taskbars.add(as_hwnd(hwnd))
        _taskbar_hidden_by_us = True
        hid = True
    if hid and not getattr(_hide_taskbars, "logged", False):
        _hide_taskbars.logged = True
        log("taskbar held")


def _restore_taskbar():
    global _taskbar_hidden_by_us, _cover_fullscreen
    hwnds = list(_hidden_taskbars)
    _hidden_taskbars.clear()
    was = _taskbar_hidden_by_us
    _taskbar_hidden_by_us = False
    _cover_fullscreen = False
    if not was and not hwnds:
        return
    for hwnd in hwnds:
        try:
            if user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, _SW_SHOWNA)
        except Exception:
            log(traceback.format_exc())
    log("taskbar restored")


def _sync_taskbar():
    try:
        _sync_taskbar_now()
    except Exception:
        if not getattr(_sync_taskbar, "logged", False):
            _sync_taskbar.logged = True
            log(traceback.format_exc())


def _sync_taskbar_now():
    form = _form
    visible = False
    try:
        visible = form is not None and form.IsHandleCreated and bool(form.Visible)
    except Exception:
        visible = False
    fg = user32.GetForegroundWindow()
    focused = visible and _veil_hwnd(fg)
    if focused:
        if _cover_fullscreen:
            _hide_taskbars()
        return
    if not fg or _veil_hwnd(fg):
        # Focus has not landed on the app underneath yet. Keep the hold.
        if _taskbar_hidden_by_us and _cover_fullscreen:
            _hide_taskbars()
        return
    if _taskbar_hidden_by_us and _window_is_fullscreen(fg):
        _hide_taskbars()
        return
    if _taskbar_hidden_by_us:
        _restore_taskbar()
    _remember_outside()


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
    global _window, _page_html, _theme
    hide_console()
    claim_single_instance()
    log("--- start pid %s test %s ---" % (os.getpid(), _test))
    APP.mkdir(parents=True, exist_ok=True)
    (APP / "webview").mkdir(parents=True, exist_ok=True)

    threading.Thread(target=hotkey_loop, name="veil-hotkey", daemon=True).start()
    hotkey_ready.wait(2)
    _theme = _read_theme()
    _render_home()
    _remember_outside()
    try:
        outside = _caption_target(_last_other)
        if outside:
            _set_transitions(outside, True)
    except Exception:
        log(traceback.format_exc())
    if _cover_fullscreen:
        _hide_taskbars()

    import webview

    x, y, width, height, maximized = place_window()
    try:
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
            background_color=THEMES[_theme]["web"],
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
    finally:
        try:
            _release_frozen_caption()
        except Exception:
            log(traceback.format_exc())
        try:
            _remove_caption_hooks()
        except Exception:
            log(traceback.format_exc())
        _restore_taskbar()


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
