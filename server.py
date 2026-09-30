import socket
from datetime import datetime

HOST = '127.0.0.1'  # Localhost
PORT = 65432        # Arbitrary non-privileged port

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"Server listening on {HOST}:{PORT}...")

    while True:
        conn, addr = server_socket.accept()
        with conn:
            print(f"Connected by {addr}")
            request = conn.recv(1024).decode()
            if request == "TIME":
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.sendall(current_time.encode())
            else:
                conn.sendall(b"Invalid request")