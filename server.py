import socket , threading, json, argparse, struct
HOST = "0.0.0.0"
PORT = 5050
MEDIA_PORT = 5051
clients = {}
client_rooms = {}
rooms = {"General"}
media_clients = {}
lock = threading.RLock()
MAX_Clients=100

def send_json(sock, payload):
    try:
        sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except (OSError, TypeError):
        return False

def read_json_line(file_obj):
    line = file_obj.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None

def send_to_user(username, payload):
    with lock:
        info = clients.get(username)
    return send_json(info["socket"], payload) if info else False

def active_users():
    with lock:
        return sorted(clients.keys(), key=str.lower)

def broadcast_user_lists():
    with lock:
        users = sorted(clients.keys(), key=str.lower)
        snapshot = {name: sorted(client_rooms.get(name, set())) for name in clients}
        room_list = sorted(rooms)
    for username in users:
        send_to_user(username, {
            "type": "users", "users": users, "rooms": room_list,
            "my_rooms": snapshot.get(username, [])
        })

def deliver_chat(sender, target, room, message, kind="text"):
    packet = {"type": "message", "sender": sender, "target": target,
              "room": room, "message": message, "kind": kind}
    if target:
        send_to_user(target, packet)
        if target != sender:
            send_to_user(sender, packet)
    else:
        with lock:
            recipients = [u for u in clients if room in client_rooms.get(u, set())]
        for username in recipients:
            send_to_user(username, packet)

def send_media_packet(sock, metadata, payload=b""):
    header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    packet = struct.pack("!I", len(header)) + header + payload
    sock.sendall(struct.pack("!I", len(packet)) + packet)

def recv_exact(sock, count):
    chunks = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def media_client_handler(sock, address):
    username = None
    try:
        file_obj = sock.makefile("r", encoding="utf-8", newline="\n")
        hello = read_json_line(file_obj)
        if not hello or hello.get("type") != "media_register":
            return
        username = str(hello.get("username", ""))
        with lock:
            if username not in clients:
                return
            old = media_clients.get(username)
            media_clients[username] = sock
        if old and old is not sock:
            try:
                old.shutdown(socket.SHUT_RDWR)
                old.close()
            except OSError:
                pass
        while True:
            length_bytes = recv_exact(sock, 4)
            if not length_bytes:
                break
            packet_len = struct.unpack("!I", length_bytes)[0]
            if packet_len < 4 or packet_len > 2_000_000:
                break
            packet = recv_exact(sock, packet_len)
            if not packet:
                break
            meta_len = struct.unpack("!I", packet[:4])[0]
            if meta_len > packet_len - 4:
                break
            try:
                metadata = json.loads(packet[4:4 + meta_len].decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            target = metadata.get("target")
            if not target:
                continue
            with lock:
                destination = media_clients.get(target)
            if destination:
                try:
                    destination.sendall(length_bytes + packet)
                except OSError:
                    pass
    except OSError:
        pass
    finally:
        if username:
            with lock:
                if media_clients.get(username) is sock:
                    media_clients.pop(username, None)
        try:
            sock.close()
        except OSError:
            pass

def media_server(host, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    print(f"Media relay listening on {host}:{port}")
    while True:
        sock, address = server.accept()
        threading.Thread(target=media_client_handler, args=(sock, address), daemon=True).start()

def handle_client(sock, address):
    username = None
    try:
        file_obj = sock.makefile("r", encoding="utf-8", newline="\n")
        hello = read_json_line(file_obj)
        if not hello:
            return
        username = str(hello.get("username", "")).strip()
        if not username or len(username) > 24 or any(c in username for c in "\r\n"):
            send_json(sock, {"type": "error", "message": "Username must be 1-24 characters."})
            return
        with lock:
            if username in clients:
                send_json(sock, {"type": "error", "message": "That username is already online."})
                return
            clients[username] = {"socket": sock, "address": address}
            client_rooms[username] = {"General"}
        send_json(sock, {"type": "system", "message": f"Welcome, {username}! Connected to the LAN chat server."})
        broadcast_user_lists()

        for line in file_obj:
            if not line:
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                send_json(sock, {"type": "error", "message": "Malformed message ignored."})
                continue
            action = data.get("type")
            if action == "chat":
                message = str(data.get("message", "")).strip()
                target = data.get("target")
                room = str(data.get("room") or "General")
                if not message:
                    continue
                if target:
                    if target not in active_users():
                        send_to_user(username, {"type": "error", "message": "That user is not online."})
                    else:
                        deliver_chat(username, target, None, message)
                else:
                    with lock:
                        joined = room in client_rooms.get(username, set())
                    if not joined:
                        send_to_user(username, {"type": "error", "message": f"Join room '{room}' before sending messages."})
                    else:
                        deliver_chat(username, None, room, message)

            elif action == "room_create":
                room = str(data.get("room", "")).strip()
                if not room or len(room) > 32:
                    send_to_user(username, {"type": "error", "message": "Room name must be 1-32 characters."})
                    continue
                with lock:
                    rooms.add(room)
                    client_rooms[username].add(room)
                deliver_chat("SERVER", None, room, f"{username} created room '{room}'.", "system")
                broadcast_user_lists()

            elif action == "room_join":
                room = str(data.get("room", "")).strip()
                with lock:
                    exists = room in rooms
                    if exists:
                        client_rooms[username].add(room)
                if not exists:
                    send_to_user(username, {"type": "error", "message": "Room does not exist. Create it first."})
                else:
                    deliver_chat("SERVER", None, room, f"{username} joined the room.", "system")
                    broadcast_user_lists()

            elif action == "room_leave":
                room = str(data.get("room", "General"))
                if room == "General":
                    send_to_user(username, {"type": "error", "message": "You cannot leave the General room."})
                else:
                    with lock:
                        client_rooms.get(username, set()).discard(room)
                    deliver_chat("SERVER", None, room, f"{username} left the room.", "system")
                    broadcast_user_lists()

            elif action == "file":
                target = data.get("target")
                room = str(data.get("room") or "General")
                name = str(data.get("name", "shared_file"))
                mime = str(data.get("mime", "application/octet-stream"))
                content = data.get("content", "")
                if len(content) > 16_000_000:
                    send_to_user(username, {"type": "error", "message": "File too large. Keep files under about 12 MB."})
                    continue
                packet = {"type": "file", "sender": username, "target": target, "room": room,
                          "name": name, "mime": mime, "content": content}
                if target:
                    if target not in active_users():
                        send_to_user(username, {"type": "error", "message": "That user is not online."})
                    else:
                        send_to_user(target, packet)
                        send_to_user(username, {"type": "system", "message": f"Sent file '{name}' to {target}."})
                else:
                    with lock:
                        recipients = [u for u in clients if room in client_rooms.get(u, set())]
                    for recipient in recipients:
                        send_to_user(recipient, packet)

            elif action == "call":
                target = data.get("target")
                mode = data.get("mode", "voice")
                if not target or target not in active_users():
                    send_to_user(username, {"type": "error", "message": "Select an online user for a call."})
                else:
                    send_to_user(target, {"type": "call", "sender": username, "mode": mode})
                    send_to_user(username, {"type": "system", "message": f"{mode.title()} call request sent to {target}."})

            elif action == "call_response":
                target = data.get("target")
                accepted = bool(data.get("accepted"))
                mode = data.get("mode", "voice")
                if target in active_users():
                    send_to_user(target, {"type": "call_response", "sender": username,
                                          "accepted": accepted, "mode": mode})

            elif action == "call_end":
                target = data.get("target")
                if target in active_users():
                    send_to_user(target, {"type": "call_end", "sender": username})

            elif action == "ping":
                send_json(sock, {"type": "pong"})
    except OSError:
        pass
    finally:
        if username:
            with lock:
                clients.pop(username, None)
                client_rooms.pop(username, None)
                media_sock = media_clients.pop(username, None)
            if media_sock:
                try:
                    media_sock.shutdown(socket.SHUT_RDWR)
                    media_sock.close()
                except OSError:
                    pass
            broadcast_user_lists()
            for user in active_users():
                send_to_user(user, {"type": "system", "message": f"{username} disconnected."})
        try:
            sock.close()
        except OSError:
            pass

def main():
    parser = argparse.ArgumentParser(description="LAN Chat Server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--media-port", type=int, default=MEDIA_PORT)
    args = parser.parse_args()
    threading.Thread(target=media_server, args=(args.host, args.media_port), daemon=True).start()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen()
    print(f"Chat server listening on {args.host}:{args.port}")
    print(f"Media relay listening on {args.host}:{args.media_port}")
    try:
        while True:
            client_sock, address = server.accept()
            threading.Thread(target=handle_client, args=(client_sock, address), daemon=True).start()
    except KeyboardInterrupt:
        print("\nServer shutting down...")
    finally:
        server.close()
if __name__ == "__main__":
    main()