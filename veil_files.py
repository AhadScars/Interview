# -*- coding: utf-8 -*-
"""This PC hosted inside Veil through the Explorer browser control."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

CLSCTX_INPROC_SERVER = 1
SBSP_ABSOLUTE = 0
SBSP_NAVIGATEBACK = 0x4000
EBO_SHOWFRAMES = 0x2
EBO_ALWAYSNAVIGATE = 0x4
EBO_NOBORDER = 0x20
FVM_AUTO = 0xFFFFFFFF
FWF_AUTOARRANGE = 0x1
FWF_NOWEBVIEW = 0x10000
SIGDN_NORMALDISPLAY = 0
SIGDN_FILESYSPATH = 0x80058000
THIS_PC = "shell:MyComputerFolder"
THIS_PC_CLSID = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"
IID_ISHELLITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
IID_IUNKNOWN = "{00000000-0000-0000-C000-000000000046}"
IID_EVENTS = "{361BBDC7-E6EE-4E13-BE58-58E2240C810F}"
E_NOINTERFACE = 0x80004002


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class FOLDERSETTINGS(ctypes.Structure):
    _fields_ = [("ViewMode", ctypes.c_uint), ("fFlags", ctypes.c_uint)]


class _Sink(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(ctypes.c_void_p))]


def _guid(text):
    guid = GUID()
    if ole32.CLSIDFromString(text, ctypes.byref(guid)) != 0:
        raise OSError("bad guid " + text)
    return guid


def _guid_bytes(text):
    guid = _guid(text)
    return ctypes.string_at(ctypes.addressof(guid), ctypes.sizeof(GUID))


def _failed(hr):
    return (int(hr) & 0xFFFFFFFF) >= 0x80000000


def _check(hr, action):
    if _failed(hr):
        raise OSError("%s failed 0x%08X" % (action, int(hr) & 0xFFFFFFFF))
    return hr


def _method(ptr, index, restype, argtypes):
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(table[index])


def _release(ptr):
    if ptr:
        _method(ptr, 2, ctypes.c_ulong, ())(ptr)


def _item_from_name(name):
    item = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(name, None, ctypes.byref(_guid(IID_ISHELLITEM)), ctypes.byref(item))
    if _failed(hr) or not item.value:
        return None
    return item.value


def _place_name(pidl):
    if not pidl:
        return ""
    for kind in (SIGDN_FILESYSPATH, SIGDN_NORMALDISPLAY):
        text = ctypes.c_void_p()
        hr = shell32.SHGetNameFromIDList(pidl, kind, ctypes.byref(text))
        if _failed(hr) or not text.value:
            continue
        try:
            return ctypes.wstring_at(text.value)
        finally:
            ole32.CoTaskMemFree(text)
    return ""


class _Events:
    def __init__(self, on_place):
        self.on_place = on_place
        self.refs = 1
        self._known = (_guid_bytes(IID_IUNKNOWN), _guid_bytes(IID_EVENTS))
        self._callbacks = []

        def query(this, riid, out):
            try:
                got = ctypes.string_at(ctypes.addressof(riid.contents), ctypes.sizeof(GUID))
                ok = got in self._known
            except Exception:
                ok = False
            if not ok:
                out[0] = None
                return E_NOINTERFACE
            out[0] = this
            self.refs += 1
            return 0

        def add(this):
            self.refs += 1
            return self.refs

        def release(this):
            self.refs -= 1
            return self.refs

        def allow(this, _pidl):
            return 0

        def created(this, _view):
            return 0

        def complete(this, pidl):
            try:
                if self.on_place:
                    self.on_place(_place_name(pidl))
            except Exception:
                pass
            return 0

        entries = (
            (ctypes.c_long, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)), query),
            (ctypes.c_ulong, (), add),
            (ctypes.c_ulong, (), release),
            (ctypes.c_long, (ctypes.c_void_p,), allow),
            (ctypes.c_long, (ctypes.c_void_p,), created),
            (ctypes.c_long, (ctypes.c_void_p,), complete),
            (ctypes.c_long, (ctypes.c_void_p,), allow),
        )
        table = (ctypes.c_void_p * len(entries))()
        for index, (restype, args, func) in enumerate(entries):
            callback = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *args)(func)
            self._callbacks.append(callback)
            table[index] = ctypes.cast(callback, ctypes.c_void_p)
        self._table = table
        self.obj = _Sink()
        self.obj.lpVtbl = ctypes.cast(self._table, ctypes.POINTER(ctypes.c_void_p))


class PcView:
    def __init__(self, on_place=None, log=None):
        self._browser = None
        self._cookie = None
        self._events = _Events(on_place)
        self._log = log or (lambda _message: None)
        self._shown = False
        self._started = False

    @property
    def visible(self):
        return self._shown

    def _log_error(self, message):
        try:
            self._log(message)
        except Exception:
            pass

    def open(self, panel, path=None):
        self._shown = True
        self._ensure(panel)
        self.sync(panel)
        if path or not self._started:
            self.browse(path)
            self._started = True

    def hide(self):
        self._shown = False

    def back(self):
        if not self._browser:
            return False
        hr = _method(self._browser, 13, ctypes.c_long, (ctypes.c_void_p, ctypes.c_uint))(
            self._browser, None, SBSP_NAVIGATEBACK
        )
        return not _failed(hr)

    def browse(self, path):
        if not self._browser:
            raise RuntimeError("This PC is not ready")
        names = []
        if path:
            names.append(path)
        else:
            names.extend((THIS_PC, THIS_PC_CLSID))
        item = None
        for name in names:
            item = _item_from_name(name)
            if item:
                break
        if not item:
            raise OSError("Could not open folder: %s" % (path or "This PC"))
        try:
            hr = _method(self._browser, 14, ctypes.c_long, (ctypes.c_void_p, ctypes.c_uint))(
                self._browser, item, SBSP_ABSOLUTE
            )
        finally:
            _release(item)
        _check(hr, "BrowseToObject")

    def sync(self, panel):
        if not self._browser or panel is None:
            return
        width = int(panel.ClientSize.Width)
        height = int(panel.ClientSize.Height)
        if width < 20 or height < 20:
            return
        rect = RECT(0, 0, width, height)
        hr = _method(self._browser, 5, ctypes.c_long, (ctypes.c_void_p, RECT))(self._browser, None, rect)
        if _failed(hr):
            self._log_error("SetRect failed 0x%08X" % (int(hr) & 0xFFFFFFFF))

    def close(self):
        browser = self._browser
        self._browser = None
        self._shown = False
        if not browser:
            return
        try:
            if self._cookie is not None:
                _method(browser, 10, ctypes.c_long, (ctypes.c_uint,))(browser, self._cookie)
        except Exception:
            pass
        self._cookie = None
        try:
            _method(browser, 4, ctypes.c_long, ())(browser)
        except Exception:
            pass
        _release(browser)

    def _ensure(self, panel):
        if self._browser:
            return
        ole32.CoInitialize(None)
        browser = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(_guid("{71F96385-DDD6-48D3-A0C1-AE06E8B055FB}")),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid("{DFD3B6B5-C10C-4BE9-85F6-A66969F402F6}")),
            ctypes.byref(browser),
        )
        _check(hr, "ExplorerBrowser")
        self._browser = browser.value
        try:
            options = EBO_SHOWFRAMES | EBO_ALWAYSNAVIGATE | EBO_NOBORDER
            hr = _method(self._browser, 11, ctypes.c_long, (ctypes.c_uint,))(self._browser, options)
            if _failed(hr):
                self._log_error("SetOptions failed 0x%08X" % (int(hr) & 0xFFFFFFFF))
            rect = RECT(0, 0, max(20, int(panel.ClientSize.Width)), max(20, int(panel.ClientSize.Height)))
            settings = FOLDERSETTINGS(FVM_AUTO, FWF_AUTOARRANGE | FWF_NOWEBVIEW)
            hwnd = int(panel.Handle.ToInt64()) & ((1 << 64) - 1)
            hr = _method(
                self._browser,
                3,
                ctypes.c_long,
                (ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.POINTER(FOLDERSETTINGS)),
            )(self._browser, hwnd, ctypes.byref(rect), ctypes.byref(settings))
            _check(hr, "Initialize")
            cookie = wintypes.DWORD()
            hr = _method(self._browser, 9, ctypes.c_long, (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)))(
                self._browser, ctypes.byref(self._events.obj), ctypes.byref(cookie)
            )
            if _failed(hr):
                self._log_error("Advise failed 0x%08X" % (int(hr) & 0xFFFFFFFF))
            else:
                self._cookie = int(cookie.value)
        except Exception:
            self.close()
            raise


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
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
ole32.CoTaskMemFree.restype = None
shell32.SHCreateItemFromParsingName.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
shell32.SHGetNameFromIDList.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
shell32.SHGetNameFromIDList.restype = ctypes.c_long
