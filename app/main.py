import argparse
import gzip
import os
import socket 
import threading

def make_response(body: bytes, content_type: str, extra_headers=None) -> bytes:
    """Build a 200 OK response with headers and a body."""
    header_text = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
    )

    if extra_headers:
        for name, value in extra_headers.items():
            header_text += f"{name}: {value}\r\n"
    header_text += "\r\n"   
    return header_text.encode() + body


OK = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
CREATED = b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n"
NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"


def read_request(connection, buffer):
    """
    Read ONE full request from the connection.
    Returns (request, leftover_buffer).
    request is None if the client hung up.
    """

    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(1024)
        if not chunk:                 
            return None, b""
        buffer += chunk


    head, _, rest = buffer.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")

    method, path, version = lines[0].split(" ")

    headers = {}
    for line in lines[1:]:
        name, value = line.split(": ", 1)
        headers[name.lower()] = value

    # 5. Body: keep receiving until we have Content-Length bytes
    content_length = int(headers.get("content-length", 0))
    while len(rest) < content_length:
        chunk = connection.recv(1024)
        if not chunk:
            return None, b""
        rest += chunk

    body = rest[:content_length]       
    leftover = rest[content_length:]   

    return (method, path, headers, body), leftover

def route(method, path, headers, body, directory):
    """Take request info, return the response bytes."""
    if method == "GET" and path == "/":
        return OK

    if method == "GET" and path.startswith("/echo/"):
        text = path[len("/echo/"):]
        response_body = text.encode()

        accept = headers.get("accept-encoding", "")
        encodings = [e.strip() for e in accept.split(",")]

        extra = {}
        if "gzip" in encodings:
            response_body = gzip.compress(response_body)
            extra["Content-Encoding"] = "gzip"

        return make_response(response_body, "text/plain", extra)

    if method == "GET" and path == "/user-agent":
        text = headers.get("user-agent", "")
        return make_response(text.encode(), "text/plain")

    if method == "GET" and path.startswith("/files/"):
        filename = path[len("/files/"):]
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                contents = f.read()
            return make_response(contents, "application/octet-stream")
        return NOT_FOUND

    if method == "POST" and path.startswith("/files/"):
        filename = path[len("/files/"):]
        file_path = os.path.join(directory, filename)
        with open(file_path, "wb") as f:
            f.write(body)
        return CREATED

    return NOT_FOUND

def handle_client(connection, directory):
    buffer = b""
    try:
        while True:
            request, buffer = read_request(connection, buffer)
            if request is None:        # client hung up → we're done
                break

            method, path, headers, body = request
            response = route(method, path, headers, body, directory)

            # Did the client ask to close after this request?
            should_close = headers.get("connection", "").lower() == "close"

            if should_close:
                # Insert "Connection: close" at the end of the headers
                # (the FIRST \r\n\r\n; the 1 means don't touch the body)
                response = response.replace(
                    b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n", 1
                )

            connection.sendall(response)

            if should_close:
                break                  # leave loop → finally closes it
    except ConnectionError:
        pass                           # client disconnected abruptly; ignore
    finally:
        connection.close()             # always runs, no matter what


def main():
    print("Logs from your program will appear here!")

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default=".")
    args = parser.parse_args()

    server_socket = socket.create_server(("localhost", 4221), reuse_port=True)

    while True:
        connection, address = server_socket.accept()
        thread = threading.Thread(
            target=handle_client, args=(connection, args.directory)
        )
        thread.start()


if __name__ == "__main__":
    main()