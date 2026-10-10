package com.g0w6y.beam;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

/** Streams one shared file to the Mac with a PUT, the same way the web page does. */
final class Uploader {

    interface Progress {
        void step(long sent, long total);
    }

    private Uploader() {}

    static String name(Context c, Uri uri) {
        String name = null;
        try (Cursor cur = c.getContentResolver().query(uri, null, null, null, null)) {
            if (cur != null && cur.moveToFirst()) {
                int i = cur.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (i >= 0 && !cur.isNull(i)) name = cur.getString(i);
            }
        } catch (Exception ignored) {}
        if (name == null || name.trim().isEmpty()) {
            name = uri.getLastPathSegment();
        }
        if (name == null || name.trim().isEmpty()) name = "shared";
        return name.replace('/', '_');
    }

    static long size(Context c, Uri uri) {
        try (Cursor cur = c.getContentResolver().query(uri, null, null, null, null)) {
            if (cur != null && cur.moveToFirst()) {
                int i = cur.getColumnIndex(OpenableColumns.SIZE);
                if (i >= 0 && !cur.isNull(i)) return cur.getLong(i);
            }
        } catch (Exception ignored) {}
        try {
            android.content.res.AssetFileDescriptor fd =
                    c.getContentResolver().openAssetFileDescriptor(uri, "r");
            if (fd != null) {
                long len = fd.getLength();
                fd.close();
                if (len >= 0 && len != android.content.res.AssetFileDescriptor.UNKNOWN_LENGTH) {
                    return len;
                }
            }
        } catch (Exception ignored) {}
        return -1;
    }

    /**
     * Send it. Beam needs a Content-Length - it refuses chunked bodies so that
     * it always knows when a transfer is complete - so a provider that will not
     * say how big the file is gets spooled to the cache first.
     */
    static void send(Context c, Uri uri, String base, String pin, Progress progress)
            throws Exception {
        String fileName = name(c, uri);
        long total = size(c, uri);
        File spool = null;
        if (total < 0) {
            spool = spool(c, uri);
            total = spool.length();
        }

        String url = base + "/up/" + URLEncoder.encode(fileName, "UTF-8").replace("+", "%20");
        if (!pin.isEmpty()) url += "?k=" + URLEncoder.encode(pin, "UTF-8");

        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        InputStream in = null;
        OutputStream out = null;
        try {
            conn.setRequestMethod("PUT");
            conn.setDoOutput(true);
            conn.setConnectTimeout(10000);
            // This mostly bounds the wait for the Mac's response once every byte
            // is sent, not the upload itself - but a weak link can also stretch
            // gaps between writes far enough to trip a short timeout, so this
            // stays generous rather than tight.
            conn.setReadTimeout(300000);
            conn.setFixedLengthStreamingMode(total);
            conn.setRequestProperty("Content-Type", "application/octet-stream");
            conn.connect();

            in = spool != null ? new java.io.FileInputStream(spool)
                               : c.getContentResolver().openInputStream(uri);
            if (in == null) throw new Exception("could not open " + fileName);
            out = conn.getOutputStream();

            byte[] buf = new byte[1 << 20];      // matches the Mac's own chunk size
            long sent = 0;
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                sent += n;
                if (progress != null) progress.step(sent, total);
            }
            out.flush();

            int code = conn.getResponseCode();
            if (code != 200) throw new Exception("the Mac answered " + code);
        } finally {
            if (in != null) try { in.close(); } catch (Exception ignored) {}
            if (out != null) try { out.close(); } catch (Exception ignored) {}
            conn.disconnect();
            if (spool != null) spool.delete();
        }
    }

    private static File spool(Context c, Uri uri) throws Exception {
        ContentResolver cr = c.getContentResolver();
        File f = new File(c.getCacheDir(), "spool-" + System.nanoTime());
        InputStream in = cr.openInputStream(uri);
        if (in == null) throw new Exception("could not read that file");
        FileOutputStream out = new FileOutputStream(f);
        byte[] buf = new byte[1 << 20];      // matches the Mac's own chunk size
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        out.close();
        in.close();
        return f;
    }
}
