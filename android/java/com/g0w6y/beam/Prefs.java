package com.g0w6y.beam;

import android.content.Context;
import android.content.SharedPreferences;

/** Where the Mac lives, and the PIN it is asking for. */
final class Prefs {

    private Prefs() {}

    static SharedPreferences of(Context c) {
        return c.getSharedPreferences("beam", Context.MODE_PRIVATE);
    }

    static String host(Context c) { return of(c).getString("host", ""); }

    static String pin(Context c) { return of(c).getString("pin", ""); }

    static void save(Context c, String host, String pin) {
        of(c).edit().putString("host", clean(host)).putString("pin", pin.trim()).apply();
    }

    /** "192.168.1.34:8080" and "http://mac.local:8080/" both mean the same thing. */
    static String clean(String host) {
        String h = host == null ? "" : host.trim();
        if (h.isEmpty()) return "";
        if (!h.startsWith("http://") && !h.startsWith("https://")) h = "http://" + h;
        while (h.endsWith("/")) h = h.substring(0, h.length() - 1);
        return h;
    }

    static boolean ready(Context c) { return !host(c).isEmpty(); }

    /** The PIN as a query string, ready to append. */
    static String key(Context c) {
        String p = pin(c);
        return p.isEmpty() ? "" : "k=" + p;
    }
}
