package com.g0w6y.beam;

import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

// Finds the Mac on this network so nobody types an address, and reports this
// phone's own address for when the phone is the one hosting.
final class Finder {

    private static final int[] PORTS = {8080, 8081, 8082, 8000};

    private Finder() {}

    // This phone's IPv4 on the WiFi or on its own hotspot, or null. WiFi and
    // access-point interfaces win over anything cellular, so hosting over a
    // hotspot with no internet lands on the right address.
    static String localIp() {
        String fallback = null;
        try {
            for (NetworkInterface nic : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (nic.isLoopback() || !nic.isUp()) continue;
                String name = nic.getName().toLowerCase();
                for (InetAddress a : Collections.list(nic.getInetAddresses())) {
                    if (!(a instanceof Inet4Address) || !a.isSiteLocalAddress()) continue;
                    String ip = a.getHostAddress();
                    if (name.startsWith("wlan") || name.startsWith("ap")
                            || name.startsWith("swlan") || name.startsWith("eth")) {
                        return ip;
                    }
                    if (fallback == null) fallback = ip;
                }
            }
        } catch (Exception ignored) {}
        return fallback;
    }

    /** "http://host:port" of the first Beam found, or null. Blocking. */
    static String scan() {
        String me = localIp();
        if (me == null) return null;
        String prefix = me.substring(0, me.lastIndexOf('.') + 1);

        final AtomicReference<String> hit = new AtomicReference<>(null);
        ExecutorService pool = Executors.newFixedThreadPool(48);
        List<Runnable> jobs = new ArrayList<>();
        for (int i = 1; i < 255; i++) {
            final String ip = prefix + i;
            jobs.add(new Runnable() {
                @Override public void run() {
                    for (int port : PORTS) {
                        if (hit.get() != null) return;
                        if (!open(ip, port)) continue;
                        if (isBeam(ip, port)) {
                            hit.compareAndSet(null, "http://" + ip + ":" + port);
                            return;
                        }
                    }
                }
            });
        }
        for (Runnable job : jobs) pool.execute(job);
        pool.shutdown();
        try {
            pool.awaitTermination(12, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {}
        pool.shutdownNow();
        return hit.get();
    }

    private static boolean open(String ip, int port) {
        Socket s = new Socket();
        try {
            s.connect(new InetSocketAddress(ip, port), 220);
            return true;
        } catch (Exception e) {
            return false;
        } finally {
            try { s.close(); } catch (Exception ignored) {}
        }
    }

    /** A Beam answers the root with its own page, PIN screen or not. */
    private static boolean isBeam(String ip, int port) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("http://" + ip + ":" + port + "/").openConnection();
            c.setConnectTimeout(900);
            c.setReadTimeout(900);
            c.setRequestMethod("GET");
            String server = c.getHeaderField("Server");
            if (server != null && server.startsWith("Beam")) return true;
            java.io.InputStream in = c.getResponseCode() >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in == null) return false;
            byte[] head = new byte[2048];
            int n = in.read(head);
            in.close();
            return n > 0 && new String(head, 0, n, "UTF-8").contains("<title>Beam</title>");
        } catch (Exception e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }
}
