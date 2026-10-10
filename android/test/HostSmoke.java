package com.g0w6y.beam;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Socket;
import java.net.URL;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Off-device test for Host: pure Java, run with the plain JDK (no Android). It
 * starts a real Host over a couple of temp files and talks to it over HTTP the
 * way a friend's browser would. Exits non-zero if anything fails.
 *
 *   javac -d /tmp/ht Host.java ../test/HostSmoke.java
 *   java  -cp /tmp/ht com.g0w6y.beam.HostSmoke
 */
public class HostSmoke {

    static int fails = 0;

    static void check(String name, boolean ok, Object detail) {
        System.out.println((ok ? "  ok   " : "  FAIL ") + name + (ok ? "" : "  <- " + detail));
        if (!ok) fails++;
    }

    static final class FileSource implements Host.Source {
        final File f;
        FileSource(File f) { this.f = f; }
        public String name() { return f.getName(); }
        public long size() { return f.length(); }
        public InputStream open() throws java.io.IOException { return new FileInputStream(f); }
    }

    public static void main(String[] args) throws Exception {
        File big = File.createTempFile("beam-host-big", ".mkv");
        File small = File.createTempFile("beam-host-small", ".txt");
        big.deleteOnExit();
        small.deleteOnExit();

        // a 40 MiB file of a repeating block, so we can check bytes by sha256
        byte[] block = new byte[65536];
        for (int i = 0; i < block.length; i++) block[i] = (byte) ("beam".charAt(i % 4));
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        long total = 40L << 20;
        try (FileOutputStream o = new FileOutputStream(big)) {
            long left = total;
            while (left > 0) {
                int n = (int) Math.min(block.length, left);
                o.write(block, 0, n);
                md.update(block, 0, n);
                left -= n;
            }
        }
        String wantHash = hex(md.digest());
        try (FileOutputStream o = new FileOutputStream(small)) {
            o.write("hello from the phone".getBytes("UTF-8"));
        }

        List<Host.Source> files = new ArrayList<>();
        files.add(new FileSource(big));
        files.add(new FileSource(small));
        String token = "Tk9Zx7Qw";
        Host host = new Host(files, token);
        int port = host.start(8090);
        String base = "http://127.0.0.1:" + port;

        try {
            // --- token gating ------------------------------------------------
            check("no token -> 404", status(base + "/") == 404, status(base + "/"));
            check("wrong token -> 404", status(base + "/WRONGTOKEN") == 404, null);
            check("a sibling path is not reachable",
                  status(base + "/" + token + "/../Host.java") == 404, null);

            // --- the listing -------------------------------------------------
            byte[] page = body(base + "/" + token);
            String html = new String(page, "UTF-8");
            check("listing shows both files",
                  html.contains(small.getName()) && html.contains(big.getName()), null);
            check("listing links carry the token", html.contains("/" + token + "/f/0/"), null);

            // --- small file, whole ------------------------------------------
            check("small file downloads intact",
                  new String(body(base + "/" + token + "/f/1/x.txt"), "UTF-8")
                          .equals("hello from the phone"), null);

            // --- big file, whole, byte-for-byte -----------------------------
            HttpURLConnection c = open(base + "/" + token + "/f/0/big.mkv");
            check("big file advertises its length",
                  c.getHeaderField("Content-Length").equals(String.valueOf(total)),
                  c.getHeaderField("Content-Length"));
            check("range is advertised", "bytes".equals(c.getHeaderField("Accept-Ranges")), null);
            MessageDigest got = MessageDigest.getInstance("SHA-256");
            InputStream in = c.getInputStream();
            byte[] buf = new byte[262144];
            long read = 0;
            int n;
            while ((n = in.read(buf)) > 0) { got.update(buf, 0, n); read += n; }
            in.close();
            check("big file is byte-for-byte identical (sha256)",
                  hex(got.digest()).equals(wantHash) && read == total, read);

            // --- ranges (video scrubbing) -----------------------------------
            HttpURLConnection r = open(base + "/" + token + "/f/0/big.mkv");
            r.setRequestProperty("Range", "bytes=1000-1099");
            check("a range request -> 206",
                  r.getResponseCode() == 206
                  && ("bytes 1000-1099/" + total).equals(r.getHeaderField("Content-Range")),
                  r.getResponseCode() + " " + r.getHeaderField("Content-Range"));
            byte[] chunk = drain(r.getInputStream());
            boolean chunkOk = chunk.length == 100;
            for (int i = 0; i < chunk.length && chunkOk; i++) {
                if (chunk[i] != block[(1000 + i) % block.length]) chunkOk = false;
            }
            check("the range bytes are the right ones", chunkOk, chunk.length);

            HttpURLConnection suf = open(base + "/" + token + "/f/0/big.mkv");
            suf.setRequestProperty("Range", "bytes=-50");
            check("a suffix range -> last 50 bytes",
                  suf.getResponseCode() == 206 && drain(suf.getInputStream()).length == 50, null);

            HttpURLConnection past = open(base + "/" + token + "/f/0/big.mkv");
            past.setRequestProperty("Range", "bytes=" + (total + 10) + "-");
            check("a range past the end -> 416", past.getResponseCode() == 416,
                  past.getResponseCode());

            // --- HEAD --------------------------------------------------------
            HttpURLConnection h = open(base + "/" + token + "/f/0/big.mkv");
            h.setRequestMethod("HEAD");
            check("HEAD gives the size with no body",
                  h.getResponseCode() == 200
                  && h.getHeaderField("Content-Length").equals(String.valueOf(total)),
                  h.getResponseCode());

            // --- several downloads at once ----------------------------------
            final String url = base + "/" + token + "/f/0/big.mkv";
            final AtomicInteger okc = new AtomicInteger();
            Thread[] ts = new Thread[3];
            for (int i = 0; i < ts.length; i++) {
                ts[i] = new Thread(new Runnable() {
                    public void run() {
                        try {
                            HttpURLConnection cc = open(url);
                            cc.setRequestProperty("Range", "bytes=0-999999");
                            if (cc.getResponseCode() == 206
                                    && drain(cc.getInputStream()).length == 1000000) {
                                okc.incrementAndGet();
                            }
                        } catch (Exception ignored) {}
                    }
                });
            }
            for (Thread t : ts) t.start();
            for (Thread t : ts) t.join();
            check("three downloads at once all succeed", okc.get() == 3, okc.get());

            // --- a realistic pile-up of connections that never send a request
            // (well under the cap) cannot starve a real one
            List<Socket> idle = new ArrayList<>();
            try {
                for (int i = 0; i < 20; i++) {
                    Socket s = new Socket("127.0.0.1", port);
                    s.setSoTimeout(1000);
                    idle.add(s);
                }
            } catch (Exception ignored) {}
            check("a real request still gets through under a moderate idle-connection pile-up",
                  status(base + "/" + token) == 200, null);

            // --- past the cap, excess connections are turned away rather than
            // piling up, and the phone recovers once they clear
            try {
                for (int i = 0; i < 80; i++) {
                    Socket s = new Socket("127.0.0.1", port);
                    s.setSoTimeout(1000);
                    idle.add(s);
                }
            } catch (Exception ignored) {}
            for (Socket s : idle) { try { s.close(); } catch (Exception ignored) {} }
            Thread.sleep(500);
            check("the host is still serving after the flood clears",
                  status(base + "/" + token) == 200, null);

            // --- a connection that sends nothing is reclaimed, not held forever
            Socket stalled = new Socket("127.0.0.1", port);
            long started = System.currentTimeMillis();
            boolean closed = false;
            try {
                stalled.setSoTimeout(30000);
                closed = stalled.getInputStream().read() == -1;   // server closed on us
            } catch (Exception ignored) {
                closed = true;                                    // reset counts too
            } finally {
                try { stalled.close(); } catch (Exception ignored) {}
            }
            long waited = System.currentTimeMillis() - started;
            check("an idle connection is reclaimed within a bounded time",
                  closed && waited < 25000, waited);

        } finally {
            host.stop();
        }

        System.out.println();
        System.out.println(fails == 0 ? "  ALL PASS" : "  " + fails + " FAILURES");
        System.exit(fails == 0 ? 0 : 1);
    }

    static HttpURLConnection open(String u) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
        c.setConnectTimeout(4000);
        c.setReadTimeout(15000);
        return c;
    }

    static int status(String u) throws Exception {
        HttpURLConnection c = open(u);
        int s = c.getResponseCode();
        c.disconnect();
        return s;
    }

    static byte[] body(String u) throws Exception {
        HttpURLConnection c = open(u);
        return drain(c.getInputStream());
    }

    static byte[] drain(InputStream in) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
        in.close();
        return b.toByteArray();
    }

    static String hex(byte[] d) {
        StringBuilder s = new StringBuilder();
        for (byte x : d) s.append(String.format("%02x", x));
        return s.toString();
    }
}
