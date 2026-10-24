# Spike — Wireless Communication System

Spike is a Python-based wireless communication application that allows multiple computers connected to the same Wi-Fi/LAN network to communicate in real time. It uses a client-server architecture to support private messaging, group chat rooms, file sharing, and voice/video calls.

## Features

- Private real-time text messaging
- Group chat rooms: create, join, leave, and chat
- Online users list
- File sharing, including images, videos, and audio files
- Real-time voice calls
- Real-time video calls using a webcam and OpenCV
- Call invitation, acceptance, decline, and hang-up
- Multithreaded server supporting multiple clients
- Graphical user interface built with Tkinter
- Separate TCP channels for chat and media

## Requirements

- Python 3.10 or newer
- Tkinter
- Microphone and speakers/headphones for voice calls
- Webcam for video calls
- Computers connected to the same reachable Wi-Fi/LAN network

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/hanzlaonline-cyber/spike.git
cd spike
```

Alternatively, download the repository as a ZIP and extract it.

### 2. Install dependencies

Create a file named `requirements.txt` containing:

```text
sounddevice
numpy
opencv-python
```

Install the required packages:

```bash
python -m pip install -r requirements.txt
```

Tkinter is normally included with Python on Windows. On Ubuntu/Debian, install it if needed:

```bash
sudo apt update
sudo apt install python3-tk
```

## How to Run

### 1. Start the server

On the host computer, run:

```bash
python server.py
```

Spike uses two TCP ports:

- **Port 5050:** Chat and control messages
- **Port 5051:** Voice and video media relay

Keep the server running while clients are connected.

### 2. Find the server's IP address

On Windows, run:

```powershell
ipconfig
```

Find the IPv4 address under your active Wi-Fi adapter.

Example: `192.168.1.10`

### 3. Start the client

On the host computer or another computer, run:

```bash
python client.py
```

If your client supports the `--server` argument, connect from another computer using:

```bash
python client.py --server 192.168.1.10
```

Replace `192.168.1.10` with the actual IP address of the host computer.

If the `--server` argument is not supported, launch the client normally and enter the server address when prompted.

Each user should choose a unique display name.

## Network and Firewall Configuration

The host computer must allow incoming TCP connections on ports 5050 and 5051.

On Windows, open Command Prompt or PowerShell as Administrator and run:

```powershell
netsh advfirewall firewall add rule name="Spike Control" dir=in action=allow protocol=TCP localport=5050

netsh advfirewall firewall add rule name="Spike Media" dir=in action=allow protocol=TCP localport=5051
```

On Ubuntu/Debian with UFW:

```bash
sudo ufw allow 5050/tcp
sudo ufw allow 5051/tcp
```

Make sure both computers can reach each other over the local network.

## Making Voice and Video Calls

1. Connect both users to the same server.
2. Select the other user from the online-users list.
3. Open the private chat.
4. Select **Voice call** or **Video call**.
5. The recipient accepts the incoming call.
6. Use **End call** to disconnect.

Ensure microphone and camera permissions are enabled. Video calling requires a working webcam, while voice calling requires an available microphone and audio output device.

## Technologies Used

- Python
- TCP Socket Programming
- Multithreading
- JSON
- Tkinter
- OpenCV
- NumPy
- SoundDevice
- Base64

## Limitations and Security

- Designed for a trusted local network; Internet-wide communication is not configured by default.
- Messages, files, and media are not encrypted.
- Login uses display names rather than secure password-based authentication.
- Media relay performance depends on network quality and server resources.
- Large file transfers and video calls may be affected by bandwidth and device performance.
- Spike is an academic project, not a production-grade messaging platform.

**Security warning:** Do not use Spike to transmit sensitive information over public or untrusted networks.

## Contributors

- Hanzla Bin Imran
- Farrukh Waseem Khan
- Ali Raza
- Alauddin

## Academic Project

Spike was developed as a Computer Networks project to demonstrate client-server architecture, TCP communication, socket programming, multithreading, file transfer, and real-time voice/video communication.

## License

No license has been specified for this repository.
