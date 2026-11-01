"""桌面捷徑會執行這支：背景啟動 App，並用 pywebview 開一個獨立視窗（工作列顯示自己的圖示）。
pywebview 失敗時，退回用 Edge/Chrome 的「App 模式」開視窗。"""
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time

APP_ID = "Willy.TwScreener"
TITLE = "我的選股王"
try:
    # 讓工作列把這個視窗當成獨立 App（不跟 Python/Edge 綁在一起），釘選時也用自己的圖示
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 5288
URL = f"http://localhost:{PORT}"
ICON = os.path.join(BASE, "static", "icon.ico")


def running():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_window_browser():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={URL}", "--window-size=1500,900"])
            return
    import webbrowser
    webbrowser.open(URL)


def set_icon(hwnd):
    """用 Win32 把視窗的大小圖示換成 static\\icon.ico"""
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
    for kind, size in ((1, 32), (0, 16)):  # ICON_BIG, ICON_SMALL
        h = user32.LoadImageW(None, ICON, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, kind, h)


def apply_icon_later():
    """等視窗出現後換圖示（只找本程序自己的、標題是 TITLE 的視窗，避免改到別的視窗）"""
    user32 = ctypes.windll.user32
    pid = os.getpid()
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
            if buf.value == TITLE:
                found.append(hwnd)
        return True

    for _ in range(100):
        user32.EnumWindows(proc(cb), 0)
        if found:
            set_icon(found[0])
            return
        time.sleep(0.1)


def open_window():
    try:
        import webview
        webview.create_window(TITLE, URL, width=1500, height=900)
        threading.Thread(target=apply_icon_later, daemon=True).start()
        # private_mode=False：保留 localStorage / cookie 等設定
        webview.start(private_mode=False)
    except Exception:
        open_window_browser()


if not running():
    log = open(os.path.join(BASE, "data", "app.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.join(BASE, "app.py")], cwd=BASE, stdout=log, stderr=log,
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                     creationflags=0x08000000)  # CREATE_NO_WINDOW：不跳出黑色視窗
    for _ in range(60):
        if running():
            break
        time.sleep(0.5)
open_window()
