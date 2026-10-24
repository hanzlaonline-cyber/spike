import argparse, base64, json, mimetypes, os, socket, struct, threading, time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog, simpledialog

BG, PANEL, PANEL2, TEXT, MUTED, FONT = "#ffffff", "#f2f2f2", "#e5e5e5", "#111111", "#555555", ("Segoe UI", 10)

def btn(parent, text, cmd, dark=False, **kw):
    return tk.Button(parent, text=text, command=cmd, relief="flat",
                     bg=TEXT if dark else PANEL2, fg="white" if dark else TEXT, **kw)

def lbl(parent, text, **kw):
    return tk.Label(parent, text=text, bg=parent["bg"], font=kw.pop("font", FONT), fg=kw.pop("fg", MUTED), **kw)

def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

#Voice/video call relayed through the server's media port.
class MediaCall: 
    def __init__(self, app, peer, mode):
        self.app, self.peer, self.mode = app, peer, mode
        self.running, self.lock = False, threading.Lock()
        self.sock = self.cap = self.mic = self.speaker = self.cv2 = None
        self.win = f"Video call with {peer} (press Q to close)"

    def start(self):
        try:
            import numpy as np, sounddevice as sd
            self.np = np
            if self.mode == "video":
                import cv2
                self.cv2 = cv2
            self.sock = socket.create_connection((self.app.host, self.app.media_port), timeout=5)
            self.sock.settimeout(None)
            self.sock.sendall((json.dumps({"type": "media_register", "username": self.app.username}) + "\n").encode())
            self.running = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            audio = dict(samplerate=16000, channels=1, dtype="int16", blocksize=1024)
            self.speaker, self.mic = sd.OutputStream(**audio), sd.InputStream(callback=self.on_audio, **audio)
            self.speaker.start(); self.mic.start()
            if self.mode == "video":
                self.cap = cv2.VideoCapture(0)
                if not self.cap.isOpened():
                    raise RuntimeError("Could not open the camera.")
                threading.Thread(target=self.video_loop, daemon=True).start()
            return True
        except Exception as exc:
            self.stop()
            messagebox.showerror("Could not start call", f"{exc}\n\nCheck dependencies, mic/camera permission and firewall ports.")
            return False

    def send_media(self, kind, payload):
        if not self.running:
            return
        meta = json.dumps({"media_type": kind, "sender": self.app.username, "target": self.peer}, separators=(",", ":")).encode()
        packet = struct.pack("!I", len(meta)) + meta + payload
        try:
            with self.lock:
                self.sock.sendall(struct.pack("!I", len(packet)) + packet)
        except OSError:
            self.running = False

    def on_audio(self, indata, frames, timing, status):
        self.send_media("audio", indata.tobytes())

    def video_loop(self):
        while self.running and self.cap:
            ok, frame = self.cap.read()
            if ok:
                ok, jpg = self.cv2.imencode(".jpg", self.cv2.resize(frame, (480, 270)), [int(self.cv2.IMWRITE_JPEG_QUALITY), 55])
                if ok:
                    self.send_media("video", jpg.tobytes())
            time.sleep(0.06)

    def receive_loop(self):
        try:
            while self.running:
                size = recv_exact(self.sock, 4)
                length = struct.unpack("!I", size)[0] if size else 0
                packet = recv_exact(self.sock, length) if 4 <= length <= 2_000_000 else None
                if not packet:
                    break
                meta_len = struct.unpack("!I", packet[:4])[0]
                meta, payload = json.loads(packet[4:4 + meta_len]), packet[4 + meta_len:]
                if meta.get("sender") == self.peer:
                    self.play(meta.get("media_type"), payload)
        except (OSError, ValueError):
            pass
        if self.running:
            self.app.root.after(0, self.app.end_call)

    def play(self, kind, payload):
        np = self.np
        try:
            if kind == "audio":
                self.speaker.write(np.frombuffer(payload, dtype=np.int16).reshape(-1, 1))
            elif kind == "video" and self.cv2:
                frame = self.cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), self.cv2.IMREAD_COLOR)
                if frame is not None:
                    self.cv2.imshow(self.win, frame)
                    if self.cv2.waitKey(1) & 255 == ord("q"):
                        self.app.root.after(0, self.app.end_call)
        except Exception:
            pass

    def stop(self):
        self.running = False
        for close in (lambda: self.mic.stop(), lambda: self.mic.close(), lambda: self.speaker.stop(),
                      lambda: self.speaker.close(), lambda: self.cap.release(),
                      lambda: self.cv2.destroyAllWindows(), lambda: self.sock.close()):
            try:
                close()
            except Exception:
                pass


class ChatClient:
    def __init__(self, root, host, port, media_port):
        self.root, self.host, self.port, self.media_port = root, host, port, media_port
        self.sock, self.username = None, ""
        self.users, self.rooms = [], ["General"]
        self.room, self.dm_user = "General", None   # current room / private chat partner
        self.history = {}                           # {("room", name) or ("dm", user): [messages]}
        self.call, self.calling, self.closing = None, False, False
        root.title("Spike"); root.geometry("1100x700"); root.minsize(850, 560); root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.show_login()

    def clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def key_of(self, p):
        """Which conversation does this message belong to?"""
        if p.get("target"):
            return ("dm", p["target"] if p["sender"] == self.username else p["sender"])
        return ("room", p.get("room") or "General")

    @property
    def view(self):
        return ("dm", self.dm_user) if self.dm_user else ("room", self.room)

    #  login 
    def show_login(self):
        self.clear()
        card = tk.Frame(self.root, bg=PANEL, padx=34, pady=30)
        card.place(relx=0.5, rely=0.5, anchor="center", width=430, height=380)
        lbl(card, "  Spike", font=("Segoe UI", 24, "bold"), fg=TEXT).pack(pady=(0, 20))
        self.fields = []
        for title, default in (("DISPLAY NAME", "User"), ("SERVER IPv4 ADDRESS", self.host)):
            lbl(card, title).pack(anchor="w")
            entry = tk.Entry(card, font=("Segoe UI", 12), bg=PANEL2, relief="flat")
            entry.insert(0, default); entry.pack(fill="x", ipady=9, pady=(5, 15))
            self.fields.append(entry)
        btn(card, "CONNECT  →", self.connect, dark=True, font=("Segoe UI", 11, "bold")).pack(fill="x", ipady=8, pady=5)
        lbl(card, "Start server.py on the host computer first.").pack()
        self.fields[0].focus_set()
        self.root.bind("<Return>", lambda e: self.connect())

    def connect(self):
        name, host = (f.get().strip() for f in self.fields)
        if not 0 < len(name) <= 24:
            return messagebox.showwarning("Invalid name", "Use 1 to 24 characters.")
        try:
            self.sock = socket.create_connection((host, self.port), timeout=5)
            self.sock.settimeout(None)
        except OSError as exc:
            return messagebox.showerror("Connection failed", f"Could not reach {host}:{self.port}\n\n{exc}")
        self.username, self.host = name, host
        self.send({"type": "login", "username": name})
        self.root.unbind("<Return>")
        self.show_main()
        threading.Thread(target=self.receive_loop, daemon=True).start()

    #  networking 
    def send(self, data):
        try:
            self.sock.sendall((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except (OSError, AttributeError):
            self.set_status("Connection lost", False)
            return False

    def receive_loop(self):
        try:
            for line in self.sock.makefile("r", encoding="utf-8", newline="\n"):
                try:
                    self.root.after(0, self.handle, json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass
        if not self.closing:
            self.root.after(0, self.set_status, "Disconnected", False)

    def handle(self, p):
        kind = p.get("type")
        if kind == "error":
            messagebox.showerror("Chat error", p.get("message", "Unknown error"))
        elif kind == "system":
            self.add_system(p.get("message", ""))
        elif kind == "users":
            self.users, self.rooms = p.get("users", []), p.get("rooms", ["General"])
            self.refresh_lists()
        elif kind == "message":
            self.store_and_show(p)
        elif kind == "file":
            self.receive_file(p)
        elif kind == "call":
            self.incoming_call(p)
        elif kind == "call_response":
            self.calling = False
            if p.get("accepted"):
                self.start_call(p["sender"], p.get("mode", "voice"))
            else:
                messagebox.showinfo("Call declined", f"{p.get('sender')} declined your call.")
        elif kind == "call_end":
            self.end_call(False, f"{p.get('sender')} ended the call.")

    #  main screen 
    def show_main(self):
        self.clear()
        header = tk.Frame(self.root, bg=PANEL, height=56)
        header.pack(fill="x"); header.pack_propagate(False)
        lbl(header, "  Spike", font=("Segoe UI", 16, "bold"), fg=TEXT).pack(side="left", padx=20)
        self.status = lbl(header, "● Connected", fg=TEXT); self.status.pack(side="right", padx=20)
        lbl(header, f"Signed in as {self.username}").pack(side="right")

        body = tk.Frame(self.root, bg=BG); body.pack(fill="both", expand=True, padx=12, pady=12)
        side = tk.Frame(body, bg=PANEL, width=235); side.pack(side="left", fill="y", padx=(0, 12)); side.pack_propagate(False)
        lbl(side, "ROOMS").pack(anchor="w", padx=14, pady=(14, 4))
        row = tk.Frame(side, bg=PANEL); row.pack(fill="x", padx=10)
        self.room_box = ttk.Combobox(row, values=self.rooms, state="readonly", width=17)
        self.room_box.set(self.room); self.room_box.pack(side="left", fill="x", expand=True)
        btn(row, "↵", self.join_room, width=3).pack(side="left", padx=(5, 0))
        btn(side, "+  Create room", self.create_room).pack(fill="x", padx=10, pady=(6, 10), ipady=4)
        lbl(side, "ONLINE USERS").pack(anchor="w", padx=14, pady=(0, 4))
        self.user_list = tk.Listbox(side, bg=PANEL2, relief="flat", font=FONT, activestyle="none",
                                    selectbackground=TEXT, selectforeground="white", exportselection=False)
        self.user_list.pack(fill="both", expand=True, padx=10)
        btn(side, "Open private chat", self.open_private, dark=True).pack(fill="x", padx=10, pady=(8, 4), ipady=5)
        btn(side, "Leave selected room", self.leave_room).pack(fill="x", padx=10, pady=(0, 10), ipady=4)

        chat = tk.Frame(body, bg=PANEL); chat.pack(side="left", fill="both", expand=True)
        top = tk.Frame(chat, bg=PANEL, height=54); top.pack(fill="x"); top.pack_propagate(False)
        self.title = lbl(top, "# General", font=("Segoe UI", 14, "bold"), fg=TEXT); self.title.pack(side="left", padx=16)
        for text, cmd, dark in (("Room chat", self.show_room, False), ("End call", self.end_call, True),
                                ("Video call", lambda: self.request_call("video"), False),
                                ("Voice call", lambda: self.request_call("voice"), False)):
            btn(top, text, cmd, dark).pack(side="right", padx=3, pady=12)

        self.messages = tk.Text(chat, bg=BG, relief="flat", wrap="word", font=FONT, padx=16, pady=12, state="disabled")
        self.messages.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.messages.tag_configure("meta", foreground=MUTED, font=("Segoe UI", 8))
        self.messages.tag_configure("name", font=("Segoe UI", 10, "bold"))
        self.messages.tag_configure("system", foreground=MUTED, font=("Segoe UI", 9, "italic"))

        bottom = tk.Frame(chat, bg=PANEL, padx=10, pady=8); bottom.pack(fill="x")
        btn(bottom, "Attach file", self.send_file).pack(anchor="w", pady=(0, 6))
        self.entry = tk.Entry(bottom, bg=PANEL2, relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.send_message())
        btn(bottom, "Send  ➤", self.send_message, dark=True, padx=18).pack(side="right", ipady=6)
        self.refresh_lists(); self.show_history()

    def set_status(self, text, ok=True):
        if hasattr(self, "status") and self.status.winfo_exists():
            self.status.configure(text="● " + text, fg=TEXT if ok else "#777777")

    def refresh_lists(self):
        if hasattr(self, "user_list") and self.user_list.winfo_exists():
            self.user_list.delete(0, tk.END)
            for u in self.users:
                self.user_list.insert(tk.END, ("◆  " if u == self.username else "●  ") + u)
            self.room_box.configure(values=self.rooms)

    #  rooms / private chats 
    def switch(self, room=None, dm_user=None):
        self.room, self.dm_user = room or self.room, dm_user
        self.title.configure(text=f"Private chat · {dm_user}" if dm_user else f"# {self.room}")
        self.show_history()

    def show_room(self):
        self.switch()

    def open_private(self):
        picked = self.user_list.curselection()
        user = self.user_list.get(picked[0])[3:].strip() if picked else None
        if not user or user == self.username:
            return messagebox.showinfo("Private chat", "Select another online user first.")
        self.switch(dm_user=user)

    def create_room(self):
        name = simpledialog.askstring("Create room", "Room name:", parent=self.root)
        if name and name.strip():
            self.send({"type": "room_create", "room": name.strip()})

    def join_room(self):
        room = self.room_box.get().strip()
        if room:
            self.send({"type": "room_join", "room": room}); self.switch(room=room)

    def leave_room(self):
        room = self.room_box.get().strip()
        if room:
            self.send({"type": "room_leave", "room": room})
            if room == self.room and room != "General":
                self.switch(room="General")

    #  messages 
    def send_message(self):
        text = self.entry.get().strip()
        if not text:
            return
        if self.dm_user:
            self.send({"type": "chat", "target": self.dm_user, "message": text})  # server echoes it back to us
        else:
            self.send({"type": "chat", "room": self.room, "message": text})
        self.entry.delete(0, tk.END)

    def store_and_show(self, p):
        p["time"] = datetime.now().strftime("%H:%M")
        key = self.key_of(p)
        self.history.setdefault(key, []).append(p)
        if key == self.view:
            self.draw(p)

    def write(self, *parts):
        """write(text, tag, text, tag, ...) at the end of the chat box."""
        self.messages.configure(state="normal")
        self.messages.insert(tk.END, *parts)
        self.messages.configure(state="disabled"); self.messages.see(tk.END)

    def draw(self, p):
        self.write(f"{p['time']}  ", "meta", f"{p['sender']}\n", "name", p.get("message", "") + "\n\n", "")

    def add_system(self, text):
        if hasattr(self, "messages") and self.messages.winfo_exists():
            self.write(f"• {text}\n", "system")

    def show_history(self):
        self.messages.configure(state="normal"); self.messages.delete("1.0", tk.END); self.messages.configure(state="disabled")
        for p in self.history.get(self.view, []):
            self.draw(p)

    #  files 
    def send_file(self):
        path = filedialog.askopenfilename(title="Choose a file to share")
        if not path:
            return
        if os.path.getsize(path) > 11 * 1024 * 1024:
            return messagebox.showwarning("File too large", "Choose a file smaller than 11 MB.")
        try:
            with open(path, "rb") as f:
                content = base64.b64encode(f.read()).decode("ascii")
        except OSError as exc:
            return messagebox.showerror("File error", str(exc))
        data = {"type": "file", "name": os.path.basename(path), "content": content,
                "mime": mimetypes.guess_type(path)[0] or "application/octet-stream"}
        data.update({"target": self.dm_user} if self.dm_user else {"room": self.room})
        if self.send(data):
            self.add_system(f"Sharing file: {data['name']}")

    def receive_file(self, p):
        sender, name = p.get("sender", "Unknown"), p.get("name", "shared_file")
        self.add_system(f"{sender} shared a file: {name}")
        if sender != self.username and self.key_of(p) == self.view and messagebox.askyesno("File received", f"{sender} shared '{name}'.\nSave it?"):
            path = filedialog.asksaveasfilename(initialfile=name)
            try:
                if path:
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(p.get("content", "")))
                    self.add_system(f"Saved file to {path}")
            except (OSError, ValueError) as exc:
                messagebox.showerror("Save failed", str(exc))

    #  calls 
    def request_call(self, mode):
        if not self.dm_user:
            return messagebox.showinfo("Choose a user", "Open a private chat with a user first.")
        if self.call or self.calling:
            return messagebox.showinfo("Call active", "Finish the current call first.")
        self.calling = True
        self.send({"type": "call", "target": self.dm_user, "mode": mode})
        self.add_system(f"Calling {self.dm_user} ({mode})…")

    def incoming_call(self, p):
        peer, mode = p.get("sender", "Unknown"), p.get("mode", "voice")
        ok = not (self.call or self.calling) and messagebox.askyesno(f"Incoming {mode} call", f"{peer} is calling you.\n\nAccept?")
        self.send({"type": "call_response", "target": peer, "accepted": ok, "mode": mode})
        if ok:
            self.start_call(peer, mode)

    def start_call(self, peer, mode):
        if self.call:
            return
        self.call = MediaCall(self, peer, mode)
        if self.call.start():
            self.set_status(f"In {mode} call with {peer}")
            self.add_system(f"{mode.title()} call connected with {peer}.")
        else:
            self.call = None

    def end_call(self, send_signal=True, note=None):
        if self.call:
            peer = self.call.peer
            self.call.stop(); self.call = None
            if send_signal:
                self.send({"type": "call_end", "target": peer})
            self.set_status("Connected"); self.add_system("Call ended.")
        if note:
            self.add_system(note)

    def close(self):
        self.closing = True
        self.end_call()
        try:
            self.sock.close()
        except (OSError, AttributeError):
            pass
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="Spike GUI Client")
    ap.add_argument("--server", default="127.0.0.1", help="Server IPv4 address")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--media-port", type=int, default=5051)
    a = ap.parse_args()
    root = tk.Tk()
    ChatClient(root, a.server, a.port, a.media_port)
    root.mainloop()


if __name__ == "__main__":
    main()