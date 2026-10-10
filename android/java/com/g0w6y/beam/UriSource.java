package com.g0w6y.beam;

import android.content.Context;
import android.net.Uri;

import java.io.IOException;
import java.io.InputStream;

// A content file, opened fresh for each download so a range can re-seek.
final class UriSource implements Host.Source {
    private final Context c;
    private final Uri uri;
    private final String name;
    private final long size;

    UriSource(Context c, Uri uri) {
        this.c = c.getApplicationContext();
        this.uri = uri;
        this.name = Uploader.name(c, uri);
        this.size = Uploader.size(c, uri);
    }

    @Override public String name() { return name; }
    @Override public long size() { return size; }

    @Override public InputStream open() throws IOException {
        InputStream in = c.getContentResolver().openInputStream(uri);
        if (in == null) throw new IOException("cannot open " + name);
        return in;
    }
}
