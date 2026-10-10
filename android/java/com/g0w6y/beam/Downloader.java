package com.g0w6y.beam;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.system.Os;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Saves a file straight from Beam to this device's own Downloads, in several
 * parallel Range requests instead of Android's single-stream DownloadManager.
 *
 * One TCP stream rarely fills a real WiFi link on its own - the same reason
 * the web page uploads three files at once (ui.py's PARALLEL). Beam's server
 * already answers byte-range requests precisely (proven by test_beam.py and
 * HostSmoke.java), so this splits a big file into several ranges, fetches
 * them at the same time, and writes each straight to its own offset in the
 * destination - a positional write (FileChannel.write with an explicit
 * position) rather than a plain stream write, so it does not move a shared
 * file pointer and concurrent writers never step on each other even though
 * they share one file and one file descriptor.
 */
final class Downloader {

    interface Progress {
        void step(long done, long total);
    }

    private static final long MIN_SPLIT = 24L << 20;   // below this, one stream is plenty
    private static final int BUF = 1 << 20;
    // A dropped connection partway through a part is retried from where it
    // actually got to, not from the start of the part - a 2 GB part does not
    // restart from zero because the last megabyte had a hiccup. 3 attempts
    // with a short, growing pause is enough to ride out a real WiFi blip
    // without turning a genuinely dead connection into a long hang.
    private static final int MAX_ATTEMPTS = 3;

    private Downloader() {}

    /** More streams earn their keep on a bigger file; not worth it on a small one. */
    static int partsFor(long total) {
        if (total < MIN_SPLIT) return 1;
        if (total < (256L << 20)) return 4;     // up to 256 MiB
        if (total < (2L << 30)) return 6;       // up to 2 GiB
        return 8;
    }

    /** Saves the file and returns the Uri it landed at. Run off the main thread. */
    static Uri save(Context c, String url, String cookie, String name, long total,
                    Progress progress) throws Exception {
        Uri dest = createDestination(c, name);
        ParcelFileDescriptor pfd = null;
        FileDescriptor fd;
        if ("file".equals(dest.getScheme())) {
            fd = new FileOutputStream(new File(dest.getPath())).getFD();
        } else {
            pfd = c.getContentResolver().openFileDescriptor(dest, "rw");
            if (pfd == null) throw new IOException("could not open " + name);
            fd = pfd.getFileDescriptor();
        }
        try {
            if (total > 0) {
                try { Os.posix_fallocate(fd, 0, total); } catch (Exception ignored) {
                    // Not fatal - the file just grows as writes land instead of up front.
                }
            }
            FileChannel channel = new FileOutputStream(fd).getChannel();
            AtomicLong done = new AtomicLong(0);
            int parts = partsFor(total);

            if (parts == 1) {
                fetchPart(url, cookie, 0, total > 0 ? total - 1 : -1, channel, done, progress, total);
            } else {
                long each = total / parts;
                Thread[] threads = new Thread[parts];
                final Exception[] failure = new Exception[1];
                for (int i = 0; i < parts; i++) {
                    final long start = i * each;
                    final long end = (i == parts - 1) ? total - 1 : (start + each - 1);
                    threads[i] = new Thread(new Runnable() {
                        @Override public void run() {
                            try {
                                fetchPart(url, cookie, start, end, channel, done, progress, total);
                            } catch (Exception e) {
                                synchronized (failure) { if (failure[0] == null) failure[0] = e; }
                            }
                        }
                    });
                    threads[i].start();
                }
                for (Thread t : threads) t.join();
                synchronized (failure) { if (failure[0] != null) throw failure[0]; }
            }

            // A thread can exit its read loop early on a connection that just
            // quietly stops instead of throwing - catching that here, rather
            // than trusting a clean return, is what stops a truncated file
            // from ever being reported as a finished one.
            if (total > 0 && done.get() != total) {
                throw new IOException("incomplete: got " + done.get() + " of " + total + " bytes");
            }
        } catch (Exception e) {
            try { c.getContentResolver().delete(dest, null, null); } catch (Exception ignored) {}
            throw e;
        } finally {
            if (pfd != null) try { pfd.close(); } catch (IOException ignored) {}
        }
        finishPending(c, dest);
        return dest;
    }

    /** One part of the file, retried from wherever it actually got to on failure. */
    private static void fetchPart(String url, String cookie, long start, long end,
                                  FileChannel channel, AtomicLong done, Progress progress,
                                  long total) throws IOException {
        long[] cursor = {start};      // how far this part has really gotten, across attempts
        IOException last = null;
        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                fetchOnce(url, cookie, cursor, end, channel, done, progress, total);
                return;
            } catch (IOException e) {
                last = e;
                if (attempt < MAX_ATTEMPTS) {
                    try { Thread.sleep(400L * attempt); } catch (InterruptedException ignored) {}
                }
            }
        }
        throw last;
    }

    /** A single HTTP request for `cursor[0]..end`; updates `cursor[0]` as bytes land, even
     *  if it ends up throwing partway through, so a retry resumes rather than repeats. */
    private static void fetchOnce(String url, String cookie, long[] cursor, long end,
                                  FileChannel channel, AtomicLong done, Progress progress,
                                  long total) throws IOException {
        long start = cursor[0];
        if (end >= 0 && start > end) return;      // this part already finished on an earlier attempt
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        try {
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(60000);
            conn.setRequestProperty("X-Beam", "1");
            if (cookie != null) conn.setRequestProperty("Cookie", cookie);
            if (end >= 0) {
                conn.setRequestProperty("Range", "bytes=" + start + "-" + end);
            } else if (start > 0) {
                conn.setRequestProperty("Range", "bytes=" + start + "-");
            }
            int code = conn.getResponseCode();
            if (code != 200 && code != 206) throw new IOException("the Mac answered " + code);
            InputStream in = conn.getInputStream();
            byte[] buf = new byte[BUF];
            int n;
            while ((n = in.read(buf)) > 0) {
                channel.write(ByteBuffer.wrap(buf, 0, n), cursor[0]);
                cursor[0] += n;
                long d = done.addAndGet(n);
                if (progress != null) progress.step(d, total);
            }
        } finally {
            conn.disconnect();
        }
    }

    private static Uri createDestination(Context c, String name) throws IOException {
        if (Build.VERSION.SDK_INT >= 29) {
            ContentResolver cr = c.getContentResolver();
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri == null) throw new IOException("could not create " + name);
            return uri;
        }
        File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        dir.mkdirs();
        return Uri.fromFile(unique(dir, name));
    }

    private static void finishPending(Context c, Uri dest) {
        if (Build.VERSION.SDK_INT < 29 || !"content".equals(dest.getScheme())) return;
        ContentValues v = new ContentValues();
        v.put(MediaStore.Downloads.IS_PENDING, 0);
        c.getContentResolver().update(dest, v, null, null);
    }

    /** `movie.mkv` -> `movie (2).mkv` if something is already sitting there (legacy path only -
     *  MediaStore does this renaming itself on API 29+). */
    private static File unique(File dir, String name) {
        File target = new File(dir, name);
        if (!target.exists()) return target;
        String stem = name, ext = "";
        int dot = name.lastIndexOf('.');
        if (dot > 0) { stem = name.substring(0, dot); ext = name.substring(dot); }
        for (int i = 2; i < 10000; i++) {
            File candidate = new File(dir, stem + " (" + i + ")" + ext);
            if (!candidate.exists()) return candidate;
        }
        return new File(dir, stem + "-" + System.nanoTime() + ext);
    }
}
