package com.g0w6y.beam;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;

// Share to Beam from any app: send the files to the Mac, or host them from this
// phone so a friend on the same WiFi downloads from a link, no Mac needed.
public class ShareActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());
    private List<Uri> shared;
    private Host host;
    private int pad;

    private TextView line, detail;
    private ProgressBar bar;
    private Button done;
    private volatile boolean cancelled = false;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle("Beam");
        pad = (int) (18 * getResources().getDisplayMetrics().density);

        shared = collect(getIntent());
        if (shared.isEmpty()) {
            LinearLayout root = column();
            TextView t = new TextView(this);
            t.setText("Nothing to send.");
            t.setTextColor(Color.parseColor("#101319"));
            root.addView(t);
            setContentView(root);
            return;
        }
        showChoice();
    }

    private void showChoice() {
        LinearLayout root = column();

        TextView head = new TextView(this);
        head.setText(shared.size() == 1 ? "Share this file" : "Share " + shared.size() + " files");
        head.setTextSize(18);
        head.setTextColor(Color.parseColor("#101319"));
        root.addView(head);

        if (Prefs.ready(this)) {
            Button toMac = big("Send to my Mac");
            toMac.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View v) { showUpload(); }
            });
            root.addView(toMac);
        }

        Button hostIt = big("Share without a Mac");
        hostIt.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { startHosting(); }
        });
        root.addView(hostIt);

        TextView hint = new TextView(this);
        hint.setText("Share without a Mac turns this phone into the sender, so a friend "
                + "on the same WiFi opens a link and downloads. No internet needed.");
        hint.setTextColor(Color.parseColor("#59616F"));
        hint.setPadding(0, pad, 0, 0);
        root.addView(hint);

        setContentView(root);
    }

    private void startHosting() {
        String ip = Finder.localIp();
        if (ip == null) {
            Toast.makeText(this, "Join a WiFi or turn on a hotspot first", Toast.LENGTH_LONG).show();
            return;
        }
        // The activity holds the read-grant for the shared files (it is per app,
        // so the host's threads can read them too), so the host lives here.
        List<Host.Source> sources = new ArrayList<>();
        for (Uri u : shared) sources.add(new UriSource(this, u));
        host = new Host(sources, token());
        int port;
        try {
            port = host.start(8080);
        } catch (Exception e) {
            host = null;
            Toast.makeText(this, "Could not start hosting: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
            return;
        }
        // A foreground service keeps the process up while you leave to send the
        // link. It carries no URI, so there is nothing to re-grant and no crash.
        try {
            Intent keep = new Intent(this, HostService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(keep);
            else startService(keep);
        } catch (Exception ignored) {}
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        showHosting("http://" + ip + ":" + port + "/" + host.token(), sources);
    }

    private void showHosting(final String link, List<Host.Source> sources) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = column();
        scroll.addView(root);

        TextView head = new TextView(this);
        head.setText("Ready to send");
        head.setTextSize(20);
        head.setTextColor(Color.parseColor("#101319"));
        root.addView(head);

        TextView sub = new TextView(this);
        sub.setText("Send this link to your friend. They open it in any browser on the "
                + "same WiFi and download. Keep this screen open.");
        sub.setTextColor(Color.parseColor("#59616F"));
        sub.setPadding(0, pad / 3, 0, pad);
        root.addView(sub);

        TextView linkView = new TextView(this);
        linkView.setText(link);
        linkView.setTextSize(16);
        linkView.setTextColor(Color.parseColor("#1A6DFF"));
        linkView.setPadding(pad / 2, pad / 2, pad / 2, pad / 2);
        linkView.setBackgroundColor(Color.parseColor("#EEF2FF"));
        linkView.setTextIsSelectable(true);
        root.addView(linkView);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        buttons.setPadding(0, pad / 2, 0, 0);
        Button copy = new Button(this);
        copy.setText("Copy link");
        copy.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("Beam link", link));
                Toast.makeText(ShareActivity.this, "Link copied", Toast.LENGTH_SHORT).show();
            }
        });
        Button share = new Button(this);
        share.setText("Send link");
        share.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                Intent i = new Intent(Intent.ACTION_SEND);
                i.setType("text/plain");
                i.putExtra(Intent.EXTRA_TEXT, link);
                startActivity(Intent.createChooser(i, "Send link"));
            }
        });
        buttons.addView(copy);
        buttons.addView(share);
        root.addView(buttons);

        TextView filesHead = new TextView(this);
        filesHead.setText("Sharing");
        filesHead.setTextColor(Color.parseColor("#8A92A2"));
        filesHead.setPadding(0, pad, 0, pad / 3);
        root.addView(filesHead);
        for (Host.Source s : sources) {
            TextView row = new TextView(this);
            long sz = s.size();
            row.setText(s.name() + (sz >= 0 ? "   " + Host.human(sz) : ""));
            row.setTextColor(Color.parseColor("#101319"));
            row.setPadding(0, pad / 4, 0, pad / 4);
            root.addView(row);
        }

        Button stop = big("Stop sharing");
        stop.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { stopHosting(); finish(); }
        });
        root.addView(stop);

        setContentView(scroll);
    }

    private void stopHosting() {
        if (host != null) { host.stop(); host = null; }
        try { stopService(new Intent(this, HostService.class)); } catch (Exception ignored) {}
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override protected void onDestroy() {
        stopHosting();
        super.onDestroy();
    }

    private static String token() {
        byte[] b = new byte[12];
        new SecureRandom().nextBytes(b);
        return Base64.encodeToString(b, Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP);
    }

    private void showUpload() {
        LinearLayout root = column();
        line = new TextView(this);
        line.setTextSize(16);
        line.setTextColor(Color.parseColor("#101319"));
        root.addView(line);

        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        bar.setPadding(0, pad / 2, 0, 0);
        root.addView(bar);

        detail = new TextView(this);
        detail.setTextColor(Color.parseColor("#59616F"));
        detail.setPadding(0, pad / 3, 0, 0);
        root.addView(detail);

        done = new Button(this);
        done.setText("Cancel");
        done.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { cancelled = true; finish(); }
        });
        root.addView(done);
        setContentView(root);
        push(shared);
    }

    private List<Uri> collect(Intent intent) {
        List<Uri> out = new ArrayList<>();
        if (intent == null) return out;
        String action = intent.getAction();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri one = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (one != null) out.add(one);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> many = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (many != null) for (Uri u : many) if (u != null) out.add(u);
        }
        if (out.isEmpty() && intent.getClipData() != null) {
            ClipData clip = intent.getClipData();
            for (int i = 0; i < clip.getItemCount(); i++) {
                Uri u = clip.getItemAt(i).getUri();
                if (u != null) out.add(u);
            }
        }
        return out;
    }

    private void push(final List<Uri> files) {
        final String base = Prefs.host(this);
        final String pin = Prefs.pin(this);
        new Thread(new Runnable() {
            @Override public void run() {
                int sent = 0;
                String failure = null;
                for (int i = 0; i < files.size(); i++) {
                    if (cancelled) return;
                    final Uri uri = files.get(i);
                    final int index = i + 1;
                    final String name = Uploader.name(ShareActivity.this, uri);
                    say(files.size() == 1 ? name : name + "  (" + index + " of " + files.size() + ")");
                    try {
                        Uploader.send(ShareActivity.this, uri, base, pin, new Uploader.Progress() {
                            @Override public void step(long got, long total) {
                                if (cancelled) return;
                                final int per = total > 0 ? (int) (got * 1000 / total) : 0;
                                final String txt = human(got) + (total > 0 ? " of " + human(total) : "");
                                ui.post(new Runnable() {
                                    @Override public void run() {
                                        bar.setProgress(per);
                                        detail.setText(txt);
                                    }
                                });
                            }
                        });
                        sent++;
                    } catch (Exception e) {
                        failure = e.getMessage();
                        break;
                    }
                }
                final int total = sent;
                final String err = failure;
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (cancelled) return;
                        bar.setProgress(1000);
                        if (err == null) {
                            line.setText(total == 1 ? "Sent to the Mac"
                                                    : total + " files sent to the Mac");
                            detail.setText("They are in the shared folder.");
                        } else {
                            line.setText("That did not go through");
                            detail.setText(err);
                        }
                        done.setText("Close");
                    }
                });
            }
        }).start();
    }

    private void say(final String head) {
        ui.post(new Runnable() {
            @Override public void run() {
                line.setText(head);
                detail.setText("");
                bar.setProgress(0);
            }
        });
    }

    private LinearLayout column() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(Color.parseColor("#FFFFFF"));
        return root;
    }

    private Button big(String label) {
        Button b = new Button(this);
        b.setText(label);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = pad / 2;
        b.setLayoutParams(lp);
        return b;
    }

    static String human(long n) {
        return Host.human(n);
    }
}
