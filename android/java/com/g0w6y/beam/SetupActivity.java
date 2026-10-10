package com.g0w6y.beam;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;

/**
 * Asks where the Mac is, or goes and finds it - and, since plenty of people
 * open this screen with no Mac anywhere nearby (out with friends, say),
 * offers the one feature that needs no Mac at all: hosting straight from
 * this phone. That path otherwise only exists inside Android's Share sheet
 * from another app, which nothing here used to point to.
 */
public class SetupActivity extends Activity {

    private static final int PICK_FILES = 1;

    private EditText hostBox, pinBox;
    private TextView status;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(Color.parseColor("#F4F5F7"));

        TextView title = new TextView(this);
        title.setText("Beam");
        title.setTextSize(30);
        title.setTextColor(Color.parseColor("#101319"));
        root.addView(title);

        TextView blurb = new TextView(this);
        blurb.setText("Open Beam on the Mac: the address and PIN are printed under "
                + "the QR code in its sidebar. Or let the phone go and find it.");
        blurb.setTextColor(Color.parseColor("#59616F"));
        blurb.setPadding(0, pad / 3, 0, pad);
        root.addView(blurb);

        TextView noMac = new TextView(this);
        noMac.setText("No Mac around right now? Pick a file below and send it straight "
                + "to a nearby phone instead - no PIN, no address, no Mac needed.");
        noMac.setTextColor(Color.parseColor("#59616F"));
        noMac.setPadding(0, 0, 0, pad / 2);
        root.addView(noMac);

        Button pick = new Button(this);
        pick.setText("Share a file with a nearby phone");
        pick.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { pickFiles(); }
        });
        root.addView(pick);

        TextView divider = new TextView(this);
        divider.setText("or connect to a Mac");
        divider.setTextColor(Color.parseColor("#8A92A2"));
        divider.setGravity(Gravity.CENTER_HORIZONTAL);
        divider.setPadding(0, pad, 0, pad / 2);
        root.addView(divider);

        hostBox = new EditText(this);
        hostBox.setHint("192.168.1.34:8080");
        hostBox.setSingleLine(true);
        hostBox.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        hostBox.setText(Prefs.host(this));
        root.addView(hostBox);

        pinBox = new EditText(this);
        pinBox.setHint("PIN");
        pinBox.setSingleLine(true);
        pinBox.setInputType(InputType.TYPE_CLASS_NUMBER);
        pinBox.setText(Prefs.pin(this));
        root.addView(pinBox);

        Button find = new Button(this);
        find.setText("Find my Mac");
        root.addView(find);

        Button save = new Button(this);
        save.setText("Save");
        root.addView(save);

        status = new TextView(this);
        status.setPadding(0, pad / 2, 0, 0);
        status.setGravity(Gravity.CENTER_HORIZONTAL);
        status.setTextColor(Color.parseColor("#59616F"));
        root.addView(status);

        setContentView(root);

        find.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { hunt(v); }
        });
        save.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { keep(); }
        });

        // First run with no address yet: go and find it, so all that is left to
        // type is the PIN.
        if (Prefs.host(this).isEmpty()) hunt(find);
    }

    /** Lets the file picker choose anything, one file or several. */
    private void pickFiles() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(Intent.createChooser(i, "Pick files to share"), PICK_FILES);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_FILES || result != RESULT_OK || data == null) return;

        ArrayList<Uri> picked = new ArrayList<>();
        if (data.getClipData() != null) {
            android.content.ClipData clip = data.getClipData();
            for (int i = 0; i < clip.getItemCount(); i++) {
                Uri u = clip.getItemAt(i).getUri();
                if (u != null) picked.add(u);
            }
        } else if (data.getData() != null) {
            picked.add(data.getData());
        }
        if (picked.isEmpty()) return;

        // Hand the picked files to ShareActivity exactly the way Android's own
        // Share sheet would - it already knows how to host and gives nothing
        // this screen does not also give it.
        Intent share = new Intent(this, ShareActivity.class);
        share.setAction(Intent.ACTION_SEND_MULTIPLE);
        share.putParcelableArrayListExtra(Intent.EXTRA_STREAM, picked);
        startActivity(share);
    }

    private void hunt(final View button) {
        button.setEnabled(false);
        status.setText("Looking on this WiFi...");
        new Thread(new Runnable() {
            @Override public void run() {
                final String found = Finder.scan();
                ui.post(new Runnable() {
                    @Override public void run() {
                        button.setEnabled(true);
                        if (found == null) {
                            status.setText("No Beam answered. Check the Mac is running it "
                                    + "and both are on the same WiFi.");
                        } else {
                            hostBox.setText(found);
                            status.setText("Found " + found);
                        }
                    }
                });
            }
        }).start();
    }

    private void keep() {
        String host = hostBox.getText().toString();
        if (Prefs.clean(host).isEmpty()) {
            Toast.makeText(this, "An address is needed", Toast.LENGTH_SHORT).show();
            return;
        }
        Prefs.save(this, host, pinBox.getText().toString());
        setResult(RESULT_OK);
        finish();
    }
}
