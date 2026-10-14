# -*- coding: utf-8 -*-
"""Silent screenshots. No sound, no toast, no Snipping Tool window."""

from __future__ import annotations

import ctypes
import time
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
VK_ESCAPE = 0x1B

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p
)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", _POINT),
        ("mouseData", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint),
        ("scanCode", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_longlong
user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
user32.SetWindowLongPtrW.restype = ctypes.c_longlong
user32.SetWindowPos.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.c_bool
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint,
]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p,
]
user32.CallNextHookEx.restype = ctypes.c_longlong
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = ctypes.c_bool


def virtual_screen():
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _hwnd(control):
    return int(control.Handle.ToInt64()) & ((1 << 64) - 1)


def conceal(control, click_through=False):
    hwnd = _hwnd(control)
    user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    updated = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if click_through:
        # Hit-testing skips this window, so Windows keeps the cursor it already had.
        # A crosshair is composited into the screen share even when the window is excluded.
        updated |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    else:
        updated &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
    if updated != ex:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, updated)
        user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )


def _drawing():
    import clr

    clr.AddReference("System.Drawing")
    clr.AddReference("System.Windows.Forms")


def save_capture(x, y, width, height, folder):
    """Grab one rectangle and write a PNG. Returns (path, bitmap) or (None, None)."""
    width = int(width)
    height = int(height)
    if width < 2 or height < 2:
        return None, None
    _drawing()
    from System.Drawing import Bitmap, Graphics, Size
    from System.Drawing.Imaging import ImageFormat

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / (stamp + ".png")
    extra = 2
    while path.exists():
        path = folder / ("%s-%d.png" % (stamp, extra))
        extra += 1
    bitmap = Bitmap(width, height)
    graphics = Graphics.FromImage(bitmap)
    try:
        graphics.CopyFromScreen(int(x), int(y), 0, 0, Size(width, height))
    except Exception:
        graphics.Dispose()
        bitmap.Dispose()
        raise
    graphics.Dispose()
    bitmap.Save(str(path), ImageFormat.Png)
    return path, bitmap


class RegionPick:
    """Dim cover over the whole desktop. Drag a rectangle. Esc cancels.

    The cover does not take the mouse, so the cursor stays the one already on screen.
    """

    def __init__(self, on_done, on_cancel):
        _drawing()
        import System.Windows.Forms as WinForms
        from System.Drawing import Color, Font

        self.on_done = on_done
        self.on_cancel = on_cancel
        self._drag = False
        self._open = False
        self._a = (0, 0)
        self._b = (0, 0)
        self._mouse_hook = None
        self._key_hook = None
        self._mouse_cb = None
        self._key_cb = None
        self._later_action = None
        form = WinForms.Form()
        form.ShowInTaskbar = False
        form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
        form.StartPosition = WinForms.FormStartPosition.Manual
        form.TopMost = True
        form.Opacity = 0.28
        form.BackColor = Color.Black
        form.KeyPreview = True
        form.Font = Font("Segoe UI", 12)
        form.Text = ""
        x, y, width, height = virtual_screen()
        form.SetBounds(x, y, max(1, width), max(1, height))

        def on_handle(sender, args):
            conceal(form, click_through=True)

        def on_down(sender, args):
            if self._mouse_hook or args.Button != WinForms.MouseButtons.Left:
                return
            self._drag = True
            self._a = (args.X, args.Y)
            self._b = self._a
            form.Invalidate()

        def on_move(sender, args):
            if self._mouse_hook or not self._drag:
                return
            self._b = (args.X, args.Y)
            form.Invalidate()

        def on_up(sender, args):
            if self._mouse_hook or not self._drag:
                return
            self._drag = False
            self._b = (args.X, args.Y)
            self._finish()

        def on_key(sender, args):
            if self._key_hook:
                return
            if args.KeyCode == WinForms.Keys.Escape:
                args.Handled = True
                self.cancel()

        def on_paint(sender, args):
            text = "Hissa kheenchon. Esc se band."
            brush = args.Graphics
            from System.Drawing import SolidBrush
            ink = SolidBrush(Color.FromArgb(255, 236, 228, 210))
            brush.DrawString(text, form.Font, ink, 24, 20)
            ink.Dispose()
            if not self._drag and self._a == self._b:
                return
            left = min(self._a[0], self._b[0])
            top = min(self._a[1], self._b[1])
            width = abs(self._b[0] - self._a[0])
            height = abs(self._b[1] - self._a[1])
            from System.Drawing import Pen
            pen = Pen(Color.FromArgb(255, 224, 177, 90), 2)
            brush.DrawRectangle(pen, left, top, width, height)
            pen.Dispose()

        form.HandleCreated += on_handle
        form.MouseDown += on_down
        form.MouseMove += on_move
        form.MouseUp += on_up
        form.KeyDown += on_key
        form.Paint += on_paint
        self.form = form
        self._keep = (on_handle, on_down, on_move, on_up, on_key, on_paint, form.Font)

    @property
    def active(self):
        return self._open

    def _client(self, sx, sy):
        bounds = self.form.Bounds
        return int(sx) - int(bounds.X), int(sy) - int(bounds.Y)

    def _pass(self, hook, nCode, wParam, lParam):
        if not hook:
            return 0
        return user32.CallNextHookEx(hook, nCode, wParam, lParam)

    def _on_mouse(self, nCode, wParam, lParam):
        if nCode < 0 or not self._open:
            return self._pass(self._mouse_hook, nCode, wParam, lParam)
        if wParam == WM_MOUSEMOVE:
            if self._drag and lParam:
                try:
                    pt = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents.pt
                    self._b = self._client(pt.x, pt.y)
                    self.form.Invalidate()
                except Exception:
                    pass
            return self._pass(self._mouse_hook, nCode, wParam, lParam)
        try:
            if lParam and wParam == WM_LBUTTONDOWN:
                pt = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents.pt
                self._drag = True
                self._a = self._client(pt.x, pt.y)
                self._b = self._a
                self.form.Invalidate()
            elif lParam and wParam == WM_LBUTTONUP and self._drag:
                pt = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents.pt
                self._drag = False
                self._b = self._client(pt.x, pt.y)
                self._later(self._finish)
        except Exception:
            pass
        return 1

    def _on_key(self, nCode, wParam, lParam):
        if nCode < 0 or not self._open:
            return self._pass(self._key_hook, nCode, wParam, lParam)
        try:
            if lParam and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if info.vkCode == VK_ESCAPE:
                    self._later(self.cancel)
                    return 1
        except Exception:
            pass
        return self._pass(self._key_hook, nCode, wParam, lParam)

    def _install_hooks(self):
        if self._mouse_hook and self._key_hook:
            return True
        self._remove_hooks()
        self._mouse_cb = HOOKPROC(self._on_mouse)
        self._key_cb = HOOKPROC(self._on_key)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb, None, 0)
        self._key_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._key_cb, None, 0)
        if not self._mouse_hook or not self._key_hook:
            self._remove_hooks()
            return False
        return True

    def _remove_hooks(self):
        mouse, key = self._mouse_hook, self._key_hook
        self._mouse_hook = None
        self._key_hook = None
        if mouse:
            user32.UnhookWindowsHookEx(mouse)
        if key:
            user32.UnhookWindowsHookEx(key)

    def _later(self, fn):
        try:
            from System import Action

            action = Action(fn)
            self._later_action = action
            if self.form.IsHandleCreated:
                self.form.BeginInvoke(action)
                return
        except Exception:
            pass
        fn()

    def _hide_window(self):
        try:
            user32.ShowWindow(_hwnd(self.form), SW_HIDE)
        except Exception:
            pass
        try:
            if self.form.Visible:
                self.form.Hide()
        except Exception:
            pass

    def start(self):
        x, y, width, height = virtual_screen()
        self._drag = False
        self._a = (0, 0)
        self._b = (0, 0)
        self.form.SetBounds(x, y, max(1, width), max(1, height))
        hwnd = _hwnd(self.form)
        hooked = self._install_hooks()
        self._open = True
        try:
            if hooked:
                conceal(self.form, click_through=True)
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                user32.SetWindowPos(
                    hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
                conceal(self.form, click_through=True)
            else:
                conceal(self.form, click_through=False)
                self.form.Show()
                self.form.TopMost = True
        except Exception:
            self._open = False
            self._remove_hooks()
            self._hide_window()
            raise

    def cancel(self):
        if not self._open:
            return
        self._open = False
        self._drag = False
        self._remove_hooks()
        self._hide_window()
        done = self.on_cancel
        if done:
            done()

    def _finish(self):
        from System.Drawing import Point

        if not self._open:
            return
        self._open = False
        self._remove_hooks()
        try:
            left = min(self._a[0], self._b[0])
            top = min(self._a[1], self._b[1])
            right = max(self._a[0], self._b[0])
            bottom = max(self._a[1], self._b[1])
            a = self.form.PointToScreen(Point(left, top))
            b = self.form.PointToScreen(Point(right, bottom))
            rect = (int(a.X), int(a.Y), int(b.X - a.X), int(b.Y - a.Y))
            wide = right - left
            tall = bottom - top
        except Exception:
            rect = None
            wide = tall = 0
        self._hide_window()
        if rect is None or wide < 8 or tall < 8:
            done = self.on_cancel
            if done:
                done()
            return
        done = self.on_done
        if done:
            done(rect)

    def close(self):
        self.on_done = None
        self.on_cancel = None
        self._open = False
        self._drag = False
        self._remove_hooks()
        try:
            self.form.Close()
        except Exception:
            pass
