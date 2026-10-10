package com.g0w6y.beam;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

// A small HTTP server that hands a fixed set of files to anyone on the same
// network who has the link. Works with no internet, over a plain hotspot too.
// Download only, token gated, ranges honoured, streamed in 1 MB blocks.
final class Host {

    interface Source {
        String name();
        long size();
        InputStream open() throws IOException;
    }

    private static final int BUF = 1 << 20;
    // A phone has far less headroom than the Mac this mirrors: a bounded pool
    // instead of one thread per connection means a flood of connections (or
    // just several friends all pulling the same big file) is turned away past
    // this point rather than spending the phone's threads and battery on it.
    private static final int MAX_CONNECTIONS = 48;
    // How long a connection may sit without finishing its request line. A real
    // browser sends one within milliseconds; this only ever fires on a
    // connection that is open and doing nothing, deliberately or not.
    private static final int IDLE_TIMEOUT_MS = 20_000;

    private final List<Source> files;
    private final String token;
    private ServerSocket socket;
    private ExecutorService pool;
    private volatile boolean running;
    private int port;

    Host(List<Source> files, String token) {
        this.files = files;
        this.token = token;
    }

    int start(int first) throws IOException {
        IOException last = null;
        for (int p = first; p < first + 20; p++) {
            try {
                ServerSocket s = new ServerSocket();
                s.setReuseAddress(true);
                try { s.setReceiveBufferSize(1 << 21); } catch (Exception ignored) {}
                s.bind(new InetSocketAddress((InetAddress) null, p));
                socket = s;
                port = p;
                break;
            } catch (IOException e) {
                last = e;
            }
        }
        if (socket == null) throw last != null ? last : new IOException("no free port");
        running = true;
        // A fixed pool with a small, bounded queue: once MAX_CONNECTIONS are
        // already being served (or briefly queued), accept() below closes the
        // next one immediately instead of spawning yet another thread for it.
        pool = new ThreadPoolExecutor(MAX_CONNECTIONS, MAX_CONNECTIONS, 30, TimeUnit.SECONDS,
                new ArrayBlockingQueue<Runnable>(8));
        Thread accept = new Thread(new Runnable() {
            @Override public void run() { acceptLoop(); }
        }, "beam-host");
        accept.setDaemon(true);
        accept.start();
        return port;
    }

    int port() { return port; }
    String token() { return token; }

    void stop() {
        running = false;
        try { if (socket != null) socket.close(); } catch (IOException ignored) {}
        if (pool != null) pool.shutdownNow();
    }

    private void acceptLoop() {
        while (running) {
            Socket c;
            try {
                c = socket.accept();
            } catch (IOException e) {
                if (running) continue;
                break;
            }
            final Socket client = c;
            try {
                client.setSoTimeout(IDLE_TIMEOUT_MS);
            } catch (Exception ignored) {}
            try {
                pool.execute(new Runnable() {
                    @Override public void run() { handle(client); }
                });
            } catch (RejectedExecutionException full) {
                // At capacity: closing it here, rather than leaving it to pile
                // up, is what keeps a flood of connections from outlasting
                // the phone's threads - a real client just retries.
                try { client.close(); } catch (IOException ignored) {}
            }
        }
    }

    private void handle(Socket c) {
        OutputStream out = null;
        try {
            c.setTcpNoDelay(true);
            try { c.setSendBufferSize(1 << 21); } catch (Exception ignored) {}
            // The timeout set on accept only bounds reading the request line
            // below; the download loop afterwards only ever writes to this
            // socket, so a slow WiFi link during the transfer itself is never
            // affected by it.
            InputStream in = new BufferedInputStream(c.getInputStream(), 8192);
            out = new BufferedOutputStream(c.getOutputStream(), BUF);
            String[] req = readHead(in);
            if (req != null) route(req[0], req[1], req[2], out);
        } catch (Throwable ignored) {
        } finally {
            if (out != null) {
                try { out.flush(); } catch (Throwable ignored) {}
            }
            try { c.close(); } catch (IOException ignored) {}
        }
    }

    private String[] readHead(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        int b;
        while ((b = in.read()) != -1) {
            sb.append((char) b);
            int n = sb.length();
            if (b == '\n' && n >= 4 && sb.charAt(n - 2) == '\r'
                    && sb.charAt(n - 3) == '\n' && sb.charAt(n - 4) == '\r') {
                break;
            }
            if (n > 16384) break;
        }
        String[] lines = sb.toString().split("\r\n");
        if (lines.length == 0 || lines[0].isEmpty()) return null;
        String[] first = lines[0].split(" ");
        if (first.length < 2) return null;
        String range = null;
        for (int i = 1; i < lines.length; i++) {
            int colon = lines[i].indexOf(':');
            if (colon > 0 && lines[i].substring(0, colon).trim().equalsIgnoreCase("Range")) {
                range = lines[i].substring(colon + 1).trim();
            }
        }
        return new String[]{first[0], first[1], range};
    }

    private void route(String method, String path, String range, OutputStream out)
            throws IOException {
        boolean head = "HEAD".equalsIgnoreCase(method);
        int q = path.indexOf('?');
        if (q >= 0) path = path.substring(0, q);
        String rel = path.startsWith("/") ? path.substring(1) : path;
        String[] parts = rel.split("/");

        if (parts.length == 0 || !constEquals(parts[0], token)) {
            send(out, 404, "Not here", head);
            return;
        }
        if (parts.length == 1 || (parts.length == 2 && parts[1].isEmpty())) {
            byte[] page = listPage().getBytes(StandardCharsets.UTF_8);
            sendBytes(out, 200, "text/html; charset=utf-8", page, head);
            return;
        }
        if (parts.length >= 3 && parts[1].equals("f")) {
            int idx = parseInt(parts[2], -1);
            if (idx < 0 || idx >= files.size()) {
                send(out, 404, "No such file", head);
                return;
            }
            serveFile(files.get(idx), range, head, out);
            return;
        }
        send(out, 404, "Not here", head);
    }

    private void serveFile(Source src, String range, boolean head, OutputStream out)
            throws IOException {
        long size = src.size();
        String type = mime(src.name());
        String disp = "attachment; filename*=UTF-8''" + urlEncode(src.name());

        // Open the source before any header goes out, so a source that cannot be
        // read becomes a clean error instead of a dropped connection.
        InputStream in = null;
        if (!head) {
            try {
                in = src.open();
            } catch (Throwable e) {
                send(out, 500, "cannot read this file: " + e, false);
                return;
            }
        }
        try {
            if (size < 0) {
                String h = "HTTP/1.1 200 OK\r\nContent-Type: " + type
                        + "\r\nContent-Disposition: " + disp
                        + "\r\nAccept-Ranges: none\r\nConnection: close\r\n\r\n";
                out.write(h.getBytes(StandardCharsets.UTF_8));
                if (!head) copyStream(in, out);
                return;
            }

            long start = 0, end = size - 1;
            boolean partial = false;
            if (range != null && range.startsWith("bytes=")) {
                String r = range.substring(6).trim();
                int dash = r.indexOf('-');
                if (dash >= 0) {
                    String a = r.substring(0, dash).trim(), b = r.substring(dash + 1).trim();
                    try {
                        if (a.isEmpty() && !b.isEmpty()) {
                            start = Math.max(size - Long.parseLong(b), 0);
                        } else if (!a.isEmpty()) {
                            start = Long.parseLong(a);
                            if (!b.isEmpty()) end = Long.parseLong(b);
                        }
                        end = Math.min(end, size - 1);
                        if (start > end || start >= size) {
                            String hdr = "HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */"
                                    + size + "\r\nConnection: close\r\nContent-Length: 0\r\n\r\n";
                            out.write(hdr.getBytes(StandardCharsets.UTF_8));
                            return;
                        }
                        partial = true;
                    } catch (NumberFormatException e) {
                        partial = false;
                        start = 0; end = size - 1;
                    }
                }
            }

            long length = end - start + 1;
            StringBuilder h = new StringBuilder();
            h.append(partial ? "HTTP/1.1 206 Partial Content\r\n" : "HTTP/1.1 200 OK\r\n");
            h.append("Content-Type: ").append(type).append("\r\n");
            h.append("Content-Length: ").append(length).append("\r\n");
            h.append("Accept-Ranges: bytes\r\n");
            if (partial) h.append("Content-Range: bytes ").append(start).append('-')
                          .append(end).append('/').append(size).append("\r\n");
            h.append("Content-Disposition: ").append(disp).append("\r\n");
            h.append("Connection: close\r\n\r\n");
            out.write(h.toString().getBytes(StandardCharsets.UTF_8));
            if (!head) {
                skip(in, start);
                copyStream(in, out, length);
            }
        } finally {
            if (in != null) try { in.close(); } catch (IOException ignored) {}
        }
    }

    private void skip(InputStream in, long start) throws IOException {
        long skipped = 0;
        while (skipped < start) {
            long s = in.skip(start - skipped);
            if (s <= 0) {
                if (in.read() == -1) return;
                s = 1;
            }
            skipped += s;
        }
    }

    private void copyStream(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[BUF];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    private void copyStream(InputStream in, OutputStream out, long length) throws IOException {
        byte[] buf = new byte[BUF];
        long left = length;
        while (left > 0) {
            int want = (int) Math.min(buf.length, left);
            int n = in.read(buf, 0, want);
            if (n <= 0) break;
            out.write(buf, 0, n);
            left -= n;
        }
    }

    private String listPage() {
        StringBuilder s = new StringBuilder();
        s.append("<!doctype html><meta charset=utf-8>")
         .append("<meta name=viewport content=\"width=device-width,initial-scale=1\">")
         .append("<title>Beam</title><style>")
         .append("body{margin:0;background:#0b0c0f;color:#e9ecf2;font:16px/1.5 -apple-system,")
         .append("BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}")
         .append(".wrap{max-width:640px;margin:0 auto;padding:22px}")
         .append("h1{font-size:22px;margin:0 0 4px}h1 i{color:#4d94ff;font-style:normal}")
         .append("p.sub{color:#a3abb9;margin:0 0 20px;font-size:14px}")
         .append("a.row{display:flex;align-items:center;gap:12px;padding:14px;margin-bottom:10px;")
         .append("background:#14161b;border:1px solid #252932;border-radius:14px;color:inherit;")
         .append("text-decoration:none}a.row:active{background:#191c22}")
         .append(".nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}")
         .append(".sz{color:#a3abb9;font-size:13px;flex:none}")
         .append(".dl{flex:none;color:#4d94ff}</style>");
        s.append("<div class=wrap><h1>Beam<i>.</i></h1>")
         .append("<p class=sub>Shared with you. Tap to download. Same WiFi only.</p>");
        for (int i = 0; i < files.size(); i++) {
            Source f = files.get(i);
            long sz = f.size();
            s.append("<a class=row href=\"/").append(token).append("/f/").append(i)
             .append('/').append(urlEncode(f.name())).append("\">")
             .append("<span class=nm>").append(escape(f.name())).append("</span>")
             .append("<span class=sz>").append(sz >= 0 ? human(sz) : "").append("</span>")
             .append("<span class=dl>&#8595;</span></a>");
        }
        s.append("</div>");
        return s.toString();
    }

    private void send(OutputStream out, int code, String body, boolean head) throws IOException {
        sendBytes(out, code, "text/plain; charset=utf-8",
                body.getBytes(StandardCharsets.UTF_8), head);
    }

    private void sendBytes(OutputStream out, int code, String type, byte[] body, boolean head)
            throws IOException {
        String reason = code == 200 ? "OK" : code == 404 ? "Not Found" : "Error";
        String h = "HTTP/1.1 " + code + " " + reason + "\r\nContent-Type: " + type
                + "\r\nContent-Length: " + body.length + "\r\nConnection: close\r\n\r\n";
        out.write(h.getBytes(StandardCharsets.UTF_8));
        if (!head) out.write(body);
    }

    private static boolean constEquals(String a, String b) {
        if (a == null || b == null || a.length() != b.length()) return false;
        int diff = 0;
        for (int i = 0; i < a.length(); i++) diff |= a.charAt(i) ^ b.charAt(i);
        return diff == 0;
    }

    private static int parseInt(String s, int fallback) {
        try { return Integer.parseInt(s); } catch (NumberFormatException e) { return fallback; }
    }

    static String human(long n) {
        String[] u = {"B", "KB", "MB", "GB", "TB"};
        double v = n;
        int i = 0;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
        return (i == 0 || v >= 100 ? String.valueOf((long) v)
                : String.format(java.util.Locale.US, "%.1f", v)) + " " + u[i];
    }

    private static String mime(String name) {
        String n = name.toLowerCase(java.util.Locale.US);
        int dot = n.lastIndexOf('.');
        String e = dot >= 0 ? n.substring(dot + 1) : "";
        switch (e) {
            case "mp4": case "m4v": return "video/mp4";
            case "mkv": return "video/x-matroska";
            case "mov": return "video/quicktime";
            case "webm": return "video/webm";
            case "avi": return "video/x-msvideo";
            case "jpg": case "jpeg": return "image/jpeg";
            case "png": return "image/png";
            case "gif": return "image/gif";
            case "webp": return "image/webp";
            case "heic": return "image/heic";
            case "mp3": return "audio/mpeg";
            case "m4a": return "audio/mp4";
            case "wav": return "audio/wav";
            case "flac": return "audio/flac";
            case "pdf": return "application/pdf";
            case "zip": return "application/zip";
            case "txt": return "text/plain; charset=utf-8";
            default: return "application/octet-stream";
        }
    }

    private static String escape(String s) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '&': b.append("&amp;"); break;
                case '<': b.append("&lt;"); break;
                case '>': b.append("&gt;"); break;
                case '"': b.append("&quot;"); break;
                default: b.append(c);
            }
        }
        return b.toString();
    }

    private static String urlEncode(String s) {
        try {
            return java.net.URLEncoder.encode(s, "UTF-8").replace("+", "%20");
        } catch (Exception e) {
            return s;
        }
    }
}
