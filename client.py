import socket

HOST = '127.0.0.1'  # Server's hostname or IP address
PORT = 65432        # Server's port

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
    client_socket.connect((HOST, PORT))
    client_socket.sendall(b"TIME")
    data = client_socket.recv(1024)

print("Current time from server:", data.decode())