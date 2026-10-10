package com.g0w6y.beam;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/**
 * The Mac's own page, in a window of its own.  Everything the browser can do
 * it can do; downloads are saved straight to the phone's own Downloads by
 * Downloader.java, in parallel Range requests rather than one single stream.
 */
public class MainActivity extends Activity {

    private static final int SETUP = 1;
    private static final int FILE_CHOOSER = 2;
    private static final String DL_CHANNEL = "beam.download";
    private static final int DL_NOTIFICATION = 2;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private boolean askedForSetup = false;
    private boolean relocating = false;
    // Android's WebView does not show a file picker for <input type=file> on
    // its own - without a WebChromeClient answering onShowFileChooser, the
    // page's "Send files" button does nothing at all, with no error either.
    // The result comes back through onActivityResult, so the callback has to
    // be held here until then.
    private ValueCallback<Uri[]> pendingFileChoice;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);

        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                return false;                       // stay inside the app
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest req,
                                                  android.webkit.WebResourceError err) {
                if (req != null && req.isForMainFrame()) unreachable();
            }
        });

        web.setDownloadListener(new DownloadListener() {
            @Override public void onDownloadStart(String url, String agent, String disposition,
                                                  String mime, long size) {
                grab(url, agent, disposition, mime, size);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> callback,
                                                       FileChooserParams params) {
                if (pendingFileChoice != null) pendingFileChoice.onReceiveValue(null);
                pendingFileChoice = callback;
                Intent i = params.createIntent();
                if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(Intent.createChooser(i, "Choose a file"), FILE_CHOOSER);
                } catch (Exception e) {
                    pendingFileChoice = null;
                    return false;
                }
                return true;
            }
        });

        setContentView(web);
        if (!Prefs.ready(this)) startSetup();
        else open();
    }

    private void open() {
        String url = Prefs.host(this) + "/";
        String key = Prefs.key(this);
        if (!key.isEmpty()) url += "?" + key;
        web.loadUrl(url);
    }

    private void startSetup() {
        askedForSetup = true;
        startActivityForResult(new Intent(this, SetupActivity.class), SETUP);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == FILE_CHOOSER) {
            if (pendingFileChoice == null) return;
            Uri[] picked = null;
            if (result == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    android.content.ClipData clip = data.getClipData();
                    picked = new Uri[clip.getItemCount()];
                    for (int i = 0; i < clip.getItemCount(); i++) picked[i] = clip.getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    picked = new Uri[]{data.getData()};
                }
            }
            pendingFileChoice.onReceiveValue(picked);
            pendingFileChoice = null;
            return;
        }
        if (request != SETUP) return;
        askedForSetup = false;
        if (Prefs.ready(this)) open();
        else finish();
    }

    /** The Mac is asleep, gone from the network, or on a different address. */
    private void unreachable() {
        if (askedForSetup || isFinishing() || relocating) return;
        // A DHCP lease often just moved the Mac to a new address. Go and find it
        // again on its own, and only bother the user if that comes up empty.
        relocating = true;
        Toast.makeText(this, "Reconnecting...", Toast.LENGTH_SHORT).show();
        new Thread(new Runnable() {
            @Override public void run() {
                final String found = Finder.scan();
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        relocating = false;
                        if (isFinishing()) return;
                        if (found != null && !found.isEmpty()) {
                            Prefs.save(MainActivity.this, found, Prefs.pin(MainActivity.this));
                            open();                 // same PIN, new address, no fuss
                        } else {
                            askToFix();
                        }
                    }
                });
            }
        }).start();
    }

    private void askToFix() {
        if (askedForSetup || isFinishing()) return;
        new AlertDialog.Builder(this)
                .setTitle("Cannot reach the Mac")
                .setMessage("Beam is not answering at " + Prefs.host(this)
                        + ".\n\nIs it running, and are both devices on the same WiFi?")
                .setPositiveButton("Change address", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) { startSetup(); }
                })
                .setNegativeButton("Try again", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) { open(); }
                })
                .setCancelable(true)
                .show();
    }

    /**
     * Saves a file to this device's own Downloads. Beam's own Downloader runs
     * several Range requests at once, which is usually a good deal faster than
     * one stream on real WiFi - the same reason the page itself uploads three
     * files at a time. Android's DownloadManager is kept as a fallback: if
     * anything about Downloader fails (an odd storage state, a very old
     * device), the file still comes down, just the ordinary single-stream way.
     */
    private void grab(final String url, String agent, String disposition, String mime, final long size) {
        final String name = URLUtil.guessFileName(url, disposition, mime);
        final String cookie = CookieManager.getInstance().getCookie(url);
        notifyProgress(name, 0, size <= 0 ? 0 : 100, null);
        Toast.makeText(this, "Saving " + name, Toast.LENGTH_SHORT).show();

        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Downloader.save(MainActivity.this, url, cookie, name, size,
                            new Downloader.Progress() {
                                private long lastShownBytes = 0;
                                private long lastShownTime = System.currentTimeMillis();
                                @Override public void step(long done, long total) {
                                    // Updating a system notification on every ~1 MB chunk
                                    // would spend more time drawing than downloading;
                                    // once every few percent is plenty to watch, and gives
                                    // a settled enough interval for the speed figure too.
                                    if (total <= 0 || done - lastShownBytes < Math.max(total / 50, 1 << 20)) return;
                                    long now = System.currentTimeMillis();
                                    long elapsedMs = Math.max(now - lastShownTime, 1);
                                    final double mbPerSec = (done - lastShownBytes) / 1024.0 / 1024.0 / (elapsedMs / 1000.0);
                                    lastShownBytes = done;
                                    lastShownTime = now;
                                    ui.post(new Runnable() {
                                        @Override public void run() {
                                            notifyProgress(name, (int) (done * 100 / total), 100,
                                                    String.format(java.util.Locale.US, "%.1f MB/s", mbPerSec));
                                        }
                                    });
                                }
                            });
                    ui.post(new Runnable() {
                        @Override public void run() {
                            finishProgress(name, true);
                        }
                    });
                } catch (Exception e) {
                    fallbackToDownloadManager(url, agent, name);
                }
            }
        }).start();
    }

    private void fallbackToDownloadManager(String url, String agent, String name) {
        try {
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) r.addRequestHeader("cookie", cookie);
            if (agent != null) r.addRequestHeader("User-Agent", agent);
            r.setTitle(name);
            r.setDescription("From Beam");
            r.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm == null) throw new IllegalStateException("no download manager");
            dm.enqueue(r);
        } catch (Exception e) {
            ui.post(new Runnable() {
                @Override public void run() { finishProgress(null, false); }
            });
        }
    }

    private void notifyProgress(String name, int percent, int max, String speed) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(
                    DL_CHANNEL, "Downloads", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, DL_CHANNEL) : new Notification.Builder(this);
        b.setContentTitle("Saving " + name)
         .setSmallIcon(android.R.drawable.stat_sys_download)
         .setOngoing(true)
         .setOnlyAlertOnce(true);
        if (speed != null) b.setContentText(speed);
        if (max > 0) b.setProgress(max, percent, false); else b.setProgress(0, 0, true);
        nm.notify(DL_NOTIFICATION, b.build());
    }

    private void finishProgress(String name, boolean ok) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (!ok) { nm.cancel(DL_NOTIFICATION); return; }
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, DL_CHANNEL) : new Notification.Builder(this);
        b.setContentTitle("Saved " + name)
         .setSmallIcon(android.R.drawable.stat_sys_download_done)
         .setOngoing(false)
         .setAutoCancel(true);
        nm.notify(DL_NOTIFICATION, b.build());
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
