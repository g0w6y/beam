package com.g0w6y.beam;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

// Keeps the app alive at foreground priority while it is hosting files, so the
// share screen (which holds the read-grant for those files) is not reclaimed
// when you switch to WhatsApp to send the link. The host itself runs in the
// activity; this service only holds the process up and shows the notification.
public class HostService extends Service {

    private static final String CHANNEL = "beam.host";
    private static final int ID = 1;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(ID, notification());
        return START_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    private Notification notification() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                    new NotificationChannel(CHANNEL, "Sharing", NotificationManager.IMPORTANCE_LOW));
        }
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        return b.setContentTitle("Beam is sharing")
                .setContentText("Tap to open")
                .setSmallIcon(android.R.drawable.stat_sys_upload)
                .setContentIntent(open)
                .setOngoing(true)
                .build();
    }
}
