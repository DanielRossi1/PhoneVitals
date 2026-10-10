package com.phonevitals.agent;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.content.AttributionSource;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.AudioRecord;
import android.media.Image;
import android.media.ImageReader;
import android.media.MediaRecorder;
import android.util.Size;
import android.view.Surface;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.BatteryManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.GnssStatus;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Agent that runs on the phone without installing any application.
 *
 * How it works. The .dex file is copied to /data/local/tmp and started with
 * app_process, the same mechanism scrcpy and Shizuku use. The resulting
 * process runs as the shell user (UID 2000), exactly like any command
 * launched from adb: it does not appear among installed applications, leaves
 * no icons, and does not survive a reboot.
 *
 * Why it is needed. Sensors are not readable from the command line: there is
 * no shell command that returns accelerometer or gyroscope values. The only
 * way is to register a SensorEventListener, and that needs a Java process
 * with a Context. This agent obtains one by calling
 * ActivityThread.systemMain(), the entry point the system itself uses to
 * build its own context.
 *
 * Protocol: one JSON line per message on stdout, read by the PC side.
 * Commands arrive on stdin, also one line per command.
 */
public final class Agent {

    private static final PrintStream OUT = System.out;
    private static final PrintStream ERR = System.err;

    /** Protocol version: the PC side checks it at startup. */
    private static final int PROTOCOL = 2;

    private static Context context;
    private static SensorManager sensorManager;

    public static void main(String[] args) {
        try {
            relaxHiddenApiRestrictions();
            Looper.prepareMainLooper();
            context = obtainContext();

            String command = args.length > 0 ? args[0] : "info";

            // One-shot commands exit explicitly: system services they touch
            // (camera, keystore) can leave non-daemon threads behind that
            // would keep the process alive after main returns.
            switch (command) {
                case "info":
                    emitInfo();
                    exit(0);
                    return;
                case "sensors":
                    streamSensors(args);
                    break;
                case "gnss":
                    streamGnss();
                    break;
                case "attest":
                    emitAttestation(args);
                    exit(0);
                    return;
                case "torch":
                    setTorch(args.length > 1 && "on".equals(args[1]),
                            args.length > 2 ? parseMillis(args[2]) : 0);
                    exit(0);
                    return;
                case "battery":
                    emitBattery(args.length > 1 ? parseCount(args[1]) : 1,
                            args.length > 2 ? parseMillis(args[2]) : 0);
                    exit(0);
                    return;
                case "tones":
                    playTones(args);
                    exit(0);
                    return;
                case "record":
                    record(args.length > 1 ? parseMillis(args[1]) : 4000);
                    exit(0);
                    return;
                case "btscan":
                    bluetoothScan(args.length > 1 ? parseMillis(args[1]) : 8000);
                    exit(0);
                    return;
                case "camera":
                    captureCameras();
                    exit(0);
                    return;
                default:
                    emitError("unknown command: " + command);
                    exit(2);
                    return;
            }

            // Started here rather than by each stream, so that a stream that
            // failed to set up still exits on "stop" or when the PC side
            // goes away, instead of idling in the loop forever.
            startCommandReader();
            Looper.loop();
        } catch (Throwable t) {
            emitFatal(t);
            System.exit(1);
        }
    }

    // -------------------------------------------------------------- context

    /**
     * Obtain a system Context without being an application.
     *
     * ActivityThread.systemMain() initialises the application thread in the
     * mode system_server uses. From there getSystemContext() returns a valid
     * Context, enough to reach system services such as SensorManager and
     * CameraManager.
     */
    private static Context obtainContext() throws Exception {
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Method systemMain = activityThread.getDeclaredMethod("systemMain");
        systemMain.setAccessible(true);
        Object thread = systemMain.invoke(null);

        Method getSystemContext = activityThread.getDeclaredMethod("getSystemContext");
        getSystemContext.setAccessible(true);
        return (Context) getSystemContext.invoke(thread);
    }

    /**
     * Disable the hidden API filter for this process.
     *
     * Since Android 9, non-public APIs are blocked at runtime. The filter can
     * be disabled for one's own process, and it is legitimate to do so: no
     * third-party code runs here, only ours. If the method does not exist
     * (Android 8 or earlier) there is nothing to disable.
     */
    private static void relaxHiddenApiRestrictions() {
        try {
            Class<?> vmRuntime = Class.forName("dalvik.system.VMRuntime");
            Method getRuntime = vmRuntime.getDeclaredMethod("getRuntime");
            getRuntime.setAccessible(true);
            Object runtime = getRuntime.invoke(null);

            Method setExemptions = vmRuntime.getDeclaredMethod(
                    "setHiddenApiExemptions", String[].class);
            setExemptions.setAccessible(true);
            // "L" as a signature prefix covers every class.
            setExemptions.invoke(runtime, (Object) new String[]{"L"});
        } catch (Throwable ignored) {
            // Not fatal: many calls work anyway.
        }
    }

    // ----------------------------------------------------------------- info

    /** Full sensor inventory, with the metadata the kernel exposes. */
    private static void emitInfo() throws Exception {
        sensorManager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);

        JSONObject root = new JSONObject();
        root.put("type", "info");
        root.put("protocol", PROTOCOL);
        root.put("sdk", android.os.Build.VERSION.SDK_INT);

        JSONArray list = new JSONArray();
        if (sensorManager != null) {
            for (Sensor s : sensorManager.getSensorList(Sensor.TYPE_ALL)) {
                list.put(describeSensor(s));
            }
        }
        root.put("sensors", list);
        emit(root);
    }

    private static JSONObject describeSensor(Sensor s) throws Exception {
        JSONObject o = new JSONObject();
        o.put("name", s.getName());
        o.put("vendor", s.getVendor());
        o.put("type", s.getType());
        o.put("stringType", s.getStringType());
        o.put("version", s.getVersion());
        o.put("power", s.getPower());
        o.put("resolution", s.getResolution());
        o.put("maxRange", s.getMaximumRange());
        o.put("minDelayUs", s.getMinDelay());
        o.put("maxDelayUs", s.getMaxDelay());
        if (android.os.Build.VERSION.SDK_INT >= 21) {
            o.put("fifoMaxEvents", s.getFifoMaxEventCount());
            o.put("fifoReservedEvents", s.getFifoReservedEventCount());
        }
        if (android.os.Build.VERSION.SDK_INT >= 24) {
            o.put("isWakeUp", s.isWakeUpSensor());
            o.put("isDynamic", s.isDynamicSensor());
            o.put("id", s.getId());
        }
        return o;
    }

    // -------------------------------------------------------------- sensors

    /**
     * Start continuous streaming of the requested sensors.
     *
     * args[1], if present, is a comma-separated list of types (the numeric
     * values of Sensor.TYPE_*). Without an argument, the sensors useful for
     * diagnostics are registered: the continuous, low-cost ones.
     */
    private static void streamSensors(String[] args) throws Exception {
        sensorManager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        if (sensorManager == null) {
            emitError("SensorManager not available");
            return;
        }

        List<Sensor> wanted = new ArrayList<>();
        if (args.length > 1 && !args[1].isEmpty()) {
            for (String part : args[1].split(",")) {
                try {
                    Sensor s = sensorManager.getDefaultSensor(Integer.parseInt(part.trim()));
                    if (s != null) {
                        wanted.add(s);
                    }
                } catch (NumberFormatException ignored) {
                }
            }
        } else {
            int[] defaults = {
                    Sensor.TYPE_ACCELEROMETER,
                    Sensor.TYPE_GYROSCOPE,
                    Sensor.TYPE_MAGNETIC_FIELD,
                    Sensor.TYPE_LIGHT,
                    Sensor.TYPE_PROXIMITY,
                    Sensor.TYPE_PRESSURE,
                    Sensor.TYPE_ROTATION_VECTOR,
                    Sensor.TYPE_GRAVITY,
                    Sensor.TYPE_LINEAR_ACCELERATION,
                    Sensor.TYPE_STEP_COUNTER,
                    Sensor.TYPE_AMBIENT_TEMPERATURE,
                    Sensor.TYPE_RELATIVE_HUMIDITY,
            };
            for (int type : defaults) {
                Sensor s = sensorManager.getDefaultSensor(type);
                if (s != null) {
                    wanted.add(s);
                }
            }
        }

        // Rate: SENSOR_DELAY_GAME is about 50 Hz, enough to see the movement
        // on screen without flooding the USB channel.
        int delay = SensorManager.SENSOR_DELAY_GAME;

        SensorEventListener listener = new SensorEventListener() {
            @Override
            public void onSensorChanged(SensorEvent event) {
                try {
                    JSONObject o = new JSONObject();
                    o.put("type", "sensor");
                    o.put("sensorType", event.sensor.getType());
                    o.put("name", event.sensor.getName());
                    o.put("accuracy", event.accuracy);
                    o.put("timestamp", event.timestamp);
                    JSONArray values = new JSONArray();
                    for (float v : event.values) {
                        values.put(Float.isNaN(v) ? JSONObject.NULL : (double) v);
                    }
                    o.put("values", values);
                    emit(o);
                } catch (Throwable ignored) {
                }
            }

            @Override
            public void onAccuracyChanged(Sensor sensor, int accuracy) {
                try {
                    JSONObject o = new JSONObject();
                    o.put("type", "accuracy");
                    o.put("sensorType", sensor.getType());
                    o.put("accuracy", accuracy);
                    emit(o);
                } catch (Throwable ignored) {
                }
            }
        };

        JSONArray registered = new JSONArray();
        for (Sensor s : wanted) {
            boolean ok = sensorManager.registerListener(listener, s, delay);
            JSONObject entry = describeSensor(s);
            entry.put("registered", ok);
            registered.put(entry);
        }

        JSONObject ready = new JSONObject();
        ready.put("type", "ready");
        ready.put("protocol", PROTOCOL);
        ready.put("streaming", registered);
        emit(ready);
    }

    /**
     * A separate thread listens on stdin for the stop command: without it the
     * process would stay alive until killed.
     */
    private static void startCommandReader() {
        // Anonymous class instead of a lambda: lambdas require
        // LambdaMetafactory, which is not part of android.jar.
        Thread reader = new Thread(new Runnable() {
            @Override
            public void run() {
                try (BufferedReader in = new BufferedReader(
                        new InputStreamReader(System.in))) {
                    String line;
                    while ((line = in.readLine()) != null) {
                        if ("stop".equals(line.trim())) {
                            System.exit(0);
                        }
                    }
                } catch (Throwable ignored) {
                }
                // stdin closed: the PC side gave up, exit.
                System.exit(0);
            }
        });
        reader.setDaemon(true);
        reader.start();
    }

    // ----------------------------------------------------------------- GNSS

    /**
     * Context attributed to the shell package.
     *
     * The context returned by `ActivityThread.getSystemContext()` claims to
     * belong to the "android" package, but the process runs as the shell user.
     * Services that check permissions compare the two and refuse: 'invalid
     * package "android" for uid 2000'. This does not happen for sensors,
     * because they need no permission; for location it does.
     *
     * Recreating the context on the `com.android.shell` package -- which is
     * what UID 2000 actually belongs to -- makes the attribution consistent
     * again and the check passes.
     *
     * A package context made from the system context still inherits "android"
     * as its op package, though, and stricter builds (seen on LineageOS 22)
     * refuse camera and microphone operations attributed that way: the
     * wrapper names the shell package everywhere the framework asks.
     */
    private static Context shellContext() {
        Context base;
        try {
            base = context.createPackageContext(
                    SHELL_PACKAGE, Context.CONTEXT_IGNORE_SECURITY);
        } catch (Throwable t) {
            base = context;
        }
        return new ShellContext(base);
    }

    private static final String SHELL_PACKAGE = "com.android.shell";

    private static final class ShellContext extends ContextWrapper {
        ShellContext(Context base) {
            super(base);
        }

        @Override
        public String getPackageName() {
            return SHELL_PACKAGE;
        }

        @Override
        public String getOpPackageName() {
            return SHELL_PACKAGE;
        }

        @Override
        public AttributionSource getAttributionSource() {
            return new AttributionSource.Builder(android.os.Process.myUid())
                    .setPackageName(SHELL_PACKAGE)
                    .build();
        }

        @Override
        public Context getApplicationContext() {
            return this;
        }
    }

    /**
     * A CameraManager bound to the shell context. getSystemService would
     * bind it to the underlying system context and its "android" identity;
     * the constructor is hidden but stable since Android 5.
     */
    private static CameraManager cameraManager() {
        Context ctx = shellContext();
        try {
            java.lang.reflect.Constructor<CameraManager> c =
                    CameraManager.class.getDeclaredConstructor(Context.class);
            c.setAccessible(true);
            return c.newInstance(ctx);
        } catch (Throwable t) {
            return (CameraManager) ctx.getSystemService(Context.CAMERA_SERVICE);
        }
    }

    /**
     * GNSS satellite status: how many are visible and at what
     * signal-to-noise ratio.
     *
     * It is worth understanding what this proves. A satellite listed with a
     * non-zero C/N0 means the antenna and receiver are demodulating a signal
     * arriving from twenty thousand kilometres away: direct proof that the
     * receive chain works, and it is obtained without having to get a position
     * fix, which indoors almost never happens. A faulty receiver, or one with
     * the antenna detached, shows zero satellites or shows them all at zero
     * C/N0.
     *
     * Registering only the status callback is not enough on many devices: the
     * GNSS engine stays off until something actually requests a position, so a
     * location update request is opened as well.
     */
    private static void streamGnss() {
        try {
            Context ctx = shellContext();
            LocationManager lm =
                    (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            if (lm == null) {
                emitError("LocationManager not available");
                return;
            }

            boolean gpsOn = false;
            try {
                gpsOn = lm.isProviderEnabled(LocationManager.GPS_PROVIDER);
            } catch (Throwable ignored) {
            }

            JSONObject note = new JSONObject();
            note.put("type", "gnss_note");
            note.put("gps_enabled", gpsOn);
            note.put("message", gpsOn
                    ? "GNSS receiver started. Satellites appear within a few "
                      + "tens of seconds; indoors the signal is heavily "
                      + "attenuated and none may be visible."
                    : "Location is disabled on the phone: the GNSS receiver "
                      + "stays off. Enable it to test the receiver.");
            emit(note);

            final Handler handler = new Handler(Looper.myLooper());

            GnssStatus.Callback statusCallback = new GnssStatus.Callback() {
                @Override
                public void onSatelliteStatusChanged(GnssStatus status) {
                    emitGnssStatus(status);
                }

                @Override
                public void onStarted() {
                    emitGnssEvent("started", -1);
                }

                @Override
                public void onStopped() {
                    emitGnssEvent("stopped", -1);
                }

                @Override
                public void onFirstFix(int ttffMillis) {
                    emitGnssEvent("first_fix", ttffMillis);
                }
            };

            // All four methods are overridden deliberately: on Android 10 and
            // earlier they are not yet default interface methods, and the
            // framework would invoke them on an object that does not implement
            // them.
            LocationListener locationListener = new LocationListener() {
                @Override
                public void onLocationChanged(Location location) {
                    try {
                        JSONObject o = new JSONObject();
                        o.put("type", "gnss_fix");
                        o.put("provider", location.getProvider());
                        o.put("accuracy_m", location.getAccuracy());
                        o.put("altitude_m", location.getAltitude());
                        o.put("satellites", location.getExtras() != null
                                ? location.getExtras().getInt("satellites", -1) : -1);
                        emit(o);
                    } catch (Throwable ignored) {
                    }
                }

                @Override
                public void onStatusChanged(String provider, int status, Bundle extras) {
                }

                @Override
                public void onProviderEnabled(String provider) {
                }

                @Override
                public void onProviderDisabled(String provider) {
                }
            };

            boolean registered = lm.registerGnssStatusCallback(statusCallback, handler);
            emitGnssEvent(registered ? "status_registered" : "status_refused", -1);
            try {
                lm.requestLocationUpdates(
                        LocationManager.GPS_PROVIDER, 1000L, 0f,
                        locationListener, Looper.myLooper());
            } catch (Throwable t) {
                // Without updates the status callback may still receive
                // something if another app keeps the engine running.
                emitError("location request refused: " + t.getMessage());
            }
        } catch (SecurityException se) {
            emitError("location permission denied to the shell process: "
                    + se.getMessage());
        } catch (Throwable t) {
            emitFatal(t);
        }
    }

    private static void emitGnssStatus(GnssStatus status) {
        try {
            int n = status.getSatelliteCount();
            JSONArray sats = new JSONArray();
            int used = 0;
            for (int i = 0; i < n; i++) {
                JSONObject x = new JSONObject();
                x.put("constellation", status.getConstellationType(i));
                x.put("svid", status.getSvid(i));
                x.put("cn0", status.getCn0DbHz(i));
                x.put("elevation", status.getElevationDegrees(i));
                x.put("azimuth", status.getAzimuthDegrees(i));
                x.put("used", status.usedInFix(i));
                x.put("almanac", status.hasAlmanacData(i));
                x.put("ephemeris", status.hasEphemerisData(i));
                if (status.usedInFix(i)) {
                    used++;
                }
                sats.put(x);
            }
            JSONObject o = new JSONObject();
            o.put("type", "gnss");
            o.put("count", n);
            o.put("used", used);
            o.put("satellites", sats);
            emit(o);
        } catch (Throwable ignored) {
        }
    }

    private static void emitGnssEvent(String event, int ttffMillis) {
        try {
            JSONObject o = new JSONObject();
            o.put("type", "gnss_event");
            o.put("event", event);
            if (ttffMillis >= 0) {
                o.put("ttff_ms", ttffMillis);
            }
            emit(o);
        } catch (Throwable ignored) {
        }
    }

    // ---------------------------------------------------- hardware attestation

    /**
     * Android Key Attestation.
     *
     * This is the strongest authenticity check a phone can offer through
     * software, and it deserves an explanation.
     *
     * The device generates a key pair inside the secure environment -- the
     * TEE, or a separate chip where StrongBox exists -- and returns a
     * certificate signed by a key the SoC vendor injected at the factory,
     * which is not extractable. Inside that certificate is an extension
     * describing the device state *as the secure environment sees it*: brand,
     * model, codename, verified boot state, whether the bootloader is locked,
     * the patch level.
     *
     * The difference from everything else we read is substantial. System
     * properties are a text file: whoever rebrands a phone rewrites them in
     * five minutes. The attested fields are signed by a key that lives in
     * hardware and that software cannot reach: forging them would mean
     * breaking the TEE. If the properties say "Samsung SM-S928B" and the
     * attestation says something else, that phone is not what it claims.
     *
     * The key generated here is disposable and deleted immediately
     * afterwards: it only serves as a pretext to obtain the certificate.
     */
    private static void emitAttestation(String[] args) {
        byte[] challenge = hexToBytes(args.length > 1 ? args[1] : "");
        if (challenge.length == 0) {
            challenge = new byte[]{'p', 'd', 'b', 'g'};
        }

        try {
            JSONObject root = new JSONObject();
            root.put("type", "attestation");
            root.put("challenge", bytesToHex(challenge));
            root.put("sdk", Build.VERSION.SDK_INT);

            JSONArray attempts = new JSONArray();
            boolean done = false;

            // StrongBox first: if the device has it, the attestation comes
            // from a chip physically separate from the application processor,
            // which is a stronger guarantee than the TEE alone.
            for (String mode : new String[]{"strongbox", "tee"}) {
                JSONObject attempt = tryAttest(mode, challenge);
                attempts.put(attempt);
                if (!done && attempt.optBoolean("ok")) {
                    root.put("chain", attempt.getJSONArray("chain"));
                    root.put("security_mode", mode);
                    root.put("device_properties_requested",
                            attempt.optBoolean("device_properties_requested"));
                    done = true;
                }
            }

            root.put("attempts", attempts);
            root.put("ok", done);
            emit(root);
        } catch (Throwable t) {
            emitFatal(t);
        }
    }

    /**
     * Register the hardware keystore crypto provider.
     *
     * In a normal application the runtime initialisation does this. Not here:
     * `app_process` starts a bare virtual machine, and without this step
     * `KeyStore.getInstance("AndroidKeyStore")` fails with "AndroidKeyStore
     * not found" -- the provider simply was never installed.
     *
     * From Android 12 the implementation moved to keystore2; on earlier
     * versions the old class applies. The new one is tried first, falling back
     * to the other.
     */
    private static void installKeystoreProvider() {
        String[] candidates = {
                "android.security.keystore2.AndroidKeyStoreProvider",
                "android.security.keystore.AndroidKeyStoreProvider",
        };
        for (String name : candidates) {
            try {
                Class<?> clazz = Class.forName(name);
                Method install = clazz.getDeclaredMethod("install");
                install.setAccessible(true);
                install.invoke(null);
                return;
            } catch (Throwable ignored) {
                // Try the next candidate.
            }
        }
    }

    private static JSONObject tryAttest(String mode, byte[] challenge) {
        JSONObject r = new JSONObject();
        String alias = "phonevitals_attest_" + mode;
        KeyStore keyStore = null;
        try {
            r.put("mode", mode);
            installKeystoreProvider();

            if ("strongbox".equals(mode) && Build.VERSION.SDK_INT < 28) {
                r.put("ok", false);
                r.put("error", "StrongBox requires Android 9 or later");
                return r;
            }

            keyStore = KeyStore.getInstance("AndroidKeyStore");
            keyStore.load(null);
            try {
                keyStore.deleteEntry(alias);
            } catch (Throwable ignored) {
            }

            // On Android 12 and later, brand, model and codename are only
            // included if explicitly requested, and not every device supports
            // it: if the first attempt fails, fall back to an attestation
            // without those fields, which is still valid for the verified boot
            // state.
            boolean canAskProperties = Build.VERSION.SDK_INT >= 31;
            Throwable last = null;

            for (int pass = 0; pass < (canAskProperties ? 2 : 1); pass++) {
                boolean withProperties = canAskProperties && pass == 0;
                try {
                    KeyGenParameterSpec.Builder builder =
                            new KeyGenParameterSpec.Builder(
                                    alias, KeyProperties.PURPOSE_SIGN)
                                    .setDigests(KeyProperties.DIGEST_SHA256)
                                    .setAttestationChallenge(challenge);
                    if ("strongbox".equals(mode)) {
                        builder.setIsStrongBoxBacked(true);
                    }
                    if (withProperties) {
                        builder.setDevicePropertiesAttestationIncluded(true);
                    }

                    KeyPairGenerator generator =
                            KeyPairGenerator.getInstance("EC", "AndroidKeyStore");
                    generator.initialize(builder.build());
                    generator.generateKeyPair();

                    Certificate[] chain = keyStore.getCertificateChain(alias);
                    if (chain == null || chain.length == 0) {
                        throw new IllegalStateException(
                                "the keystore returned no chain");
                    }

                    JSONArray encoded = new JSONArray();
                    for (Certificate c : chain) {
                        encoded.put(Base64.encodeToString(c.getEncoded(), Base64.NO_WRAP));
                    }

                    r.put("chain", encoded);
                    r.put("device_properties_requested", withProperties);
                    r.put("ok", true);
                    return r;
                } catch (Throwable t) {
                    last = t;
                    try {
                        keyStore.deleteEntry(alias);
                    } catch (Throwable ignored) {
                    }
                }
            }

            r.put("ok", false);
            r.put("error", last == null ? "unknown cause"
                    : last.getClass().getSimpleName() + ": " + last.getMessage());
        } catch (Throwable t) {
            try {
                r.put("ok", false);
                r.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
            } catch (Throwable ignored) {
            }
        } finally {
            // The key must not stay on the phone: it was only a pretext to
            // obtain the certificate.
            if (keyStore != null) {
                try {
                    keyStore.deleteEntry(alias);
                } catch (Throwable ignored) {
                }
            }
        }
        return r;
    }

    private static byte[] hexToBytes(String hex) {
        String clean = hex == null ? "" : hex.trim();
        if (clean.length() < 2 || clean.length() % 2 != 0) {
            return new byte[0];
        }
        byte[] out = new byte[clean.length() / 2];
        try {
            for (int i = 0; i < out.length; i++) {
                out[i] = (byte) Integer.parseInt(
                        clean.substring(i * 2, i * 2 + 2), 16);
            }
        } catch (NumberFormatException e) {
            return new byte[0];
        }
        return out;
    }

    private static String bytesToHex(byte[] data) {
        StringBuilder sb = new StringBuilder(data.length * 2);
        for (byte b : data) {
            sb.append(Character.forDigit((b >> 4) & 0xF, 16));
            sb.append(Character.forDigit(b & 0xF, 16));
        }
        return sb.toString();
    }

    // ----------------------------------------------------------------- torch

    /**
     * Switch the torch of the first camera that has one.
     *
     * Camera service turns the torch off as soon as the process that switched
     * it on dies, and this process exits right after the command. With
     * holdMillis > 0 the light is therefore kept on for that long, then
     * switched off explicitly before exiting.
     */
    private static void setTorch(boolean on, long holdMillis) {
        try {
            Object cm = cameraManager();
            Method getIds = cm.getClass().getMethod("getCameraIdList");
            String[] ids = (String[]) getIds.invoke(cm);
            Method setTorchMode = cm.getClass().getMethod(
                    "setTorchMode", String.class, boolean.class);
            for (String id : ids) {
                try {
                    setTorchMode.invoke(cm, id, on);
                } catch (Throwable ignored) {
                    // This camera has no flash: try the next one.
                    continue;
                }
                JSONObject o = new JSONObject();
                o.put("type", "torch");
                o.put("camera", id);
                o.put("on", on);
                emit(o);
                if (on && holdMillis > 0) {
                    try {
                        Thread.sleep(holdMillis);
                    } finally {
                        setTorchMode.invoke(cm, id, false);
                    }
                }
                return;
            }
            emitError("no camera with a flash available");
        } catch (Throwable t) {
            emitFatal(t);
        }
    }

    // --------------------------------------------------------------- battery

    // BatteryManager properties added in Android 14 as system APIs; their
    // constants are hidden from android.jar, so the values are spelled out.
    private static final int PROPERTY_MANUFACTURING_DATE = 7;
    private static final int PROPERTY_FIRST_USAGE_DATE = 8;
    private static final int PROPERTY_STATE_OF_HEALTH = 10;
    private static final String EXTRA_CYCLE_COUNT = "android.os.extra.CYCLE_COUNT";

    /**
     * What BatteryManager knows about the battery, `samples` times.
     *
     * The first sample also carries the slow-changing facts: cycle count
     * (public since Android 14), and state of health and the cell dates,
     * which need the BATTERY_STATS permission. Each is reported only when the
     * device actually provides it; a refusal is reported as such, so the PC
     * side can tell "not available" from "not allowed".
     */
    private static void emitBattery(int samples, long intervalMillis) throws Exception {
        // The shell package context: the bare system context gets no sticky
        // broadcasts back, being registered under the "android" package.
        Context ctx = shellContext();
        BatteryManager bm = (BatteryManager) ctx.getSystemService(Context.BATTERY_SERVICE);
        for (int i = 0; i < samples; i++) {
            JSONObject o = new JSONObject();
            o.put("type", "battery");
            o.put("sample", i);
            o.put("uptime_ms", android.os.SystemClock.uptimeMillis());
            // Keeps counting through deep sleep, unlike uptime.
            o.put("elapsed_ms", android.os.SystemClock.elapsedRealtime());
            // Positive values mean current flowing into the battery.
            putIfValid(o, "current_now_ua", bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW));
            putIfValid(o, "current_avg_ua", bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE));
            putIfValid(o, "charge_counter_uah", bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER));
            putIfValid(o, "capacity_percent", bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY));

            Intent sticky = null;
            try {
                sticky = ctx.registerReceiver(null,
                        new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            } catch (Throwable ignored) {
                // Not available to this process: the PC side has dumpsys.
            }
            if (sticky != null) {
                o.put("status", sticky.getIntExtra(BatteryManager.EXTRA_STATUS, -1));
                o.put("plugged", sticky.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1));
                o.put("voltage_mv", sticky.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1));
                o.put("temperature_dc", sticky.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE));
                if (i == 0 && sticky.hasExtra(EXTRA_CYCLE_COUNT)) {
                    o.put("cycle_count", sticky.getIntExtra(EXTRA_CYCLE_COUNT, -1));
                }
            }

            if (i == 0 && Build.VERSION.SDK_INT >= 34) {
                JSONObject restricted = new JSONObject();
                readLongProperty(bm, PROPERTY_STATE_OF_HEALTH, "state_of_health_percent", o, restricted);
                readLongProperty(bm, PROPERTY_MANUFACTURING_DATE, "manufacturing_date_s", o, restricted);
                readLongProperty(bm, PROPERTY_FIRST_USAGE_DATE, "first_usage_date_s", o, restricted);
                if (restricted.length() > 0) {
                    o.put("refused", restricted);
                }
            }
            emit(o);
            if (i + 1 < samples && intervalMillis > 0) {
                Thread.sleep(intervalMillis);
            }
        }
    }

    private static void readLongProperty(BatteryManager bm, int id, String key,
                                         JSONObject out, JSONObject refused) throws Exception {
        try {
            long value = bm.getLongProperty(id);
            if (value != Long.MIN_VALUE && value > 0) {
                out.put(key, value);
            }
        } catch (SecurityException e) {
            refused.put(key, String.valueOf(e.getMessage()));
        } catch (Throwable ignored) {
            // Not implemented by this device's health HAL.
        }
    }

    private static void putIfValid(JSONObject o, String key, int value) throws Exception {
        // BatteryManager answers Integer.MIN_VALUE for "not supported".
        if (value != Integer.MIN_VALUE) {
            o.put(key, value);
        }
    }

    // ----------------------------------------------------------------- tones

    private static final int SAMPLE_RATE = 48000;

    /**
     * Play a sequence of sine tones on the loudspeaker: `tones <hz,hz,...> <ms>`.
     *
     * Each tone is announced on stdout as it starts, so the PC can listen for
     * that frequency with its own microphone during that window. A quarter of
     * a second of silence separates the tones and fades avoid clicks, whose
     * broadband energy would look like a hit at every frequency.
     */
    private static void playTones(String[] args) throws Exception {
        if (args.length < 3) {
            emitError("usage: tones <hz,hz,...> <ms>");
            return;
        }
        String[] parts = args[1].split(",");
        long toneMillis = parseMillis(args[2]);
        int toneSamples = (int) (SAMPLE_RATE * toneMillis / 1000);
        int gapSamples = SAMPLE_RATE / 4;
        int fade = SAMPLE_RATE / 100;

        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build())
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setBufferSizeInBytes(SAMPLE_RATE)
                .build();
        try {
            track.play();
            short[] silence = new short[gapSamples];
            track.write(silence, 0, silence.length);
            for (String part : parts) {
                double hz = Double.parseDouble(part.trim());
                short[] pcm = new short[toneSamples];
                for (int n = 0; n < toneSamples; n++) {
                    double envelope = Math.min(1.0, Math.min(n, toneSamples - 1 - n) / (double) fade);
                    pcm[n] = (short) (0.8 * Short.MAX_VALUE * envelope
                            * Math.sin(2 * Math.PI * hz * n / SAMPLE_RATE));
                }
                JSONObject o = new JSONObject();
                o.put("type", "tone");
                o.put("hz", hz);
                o.put("ms", toneMillis);
                emit(o);
                // write() blocks while the buffer drains, which paces the
                // announcements with what is actually coming out.
                track.write(pcm, 0, pcm.length);
                track.write(silence, 0, silence.length);
            }
            Thread.sleep(300);
        } finally {
            track.stop();
            track.release();
        }
        JSONObject done = new JSONObject();
        done.put("type", "tones_done");
        emit(done);
    }

    // ------------------------------------------------------------ microphone

    private static final int RECORD_RATE = 16000;

    /**
     * Record from the default microphone for `millis` and print the PCM
     * (16 kHz, mono, 16-bit little endian) as base64. A "recording" message
     * marks the moment samples start flowing, so the PC can time its tones.
     */
    private static void record(long millis) throws Exception {
        Context ctx = shellContext();
        int min = AudioRecord.getMinBufferSize(RECORD_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec = new AudioRecord.Builder()
                .setContext(ctx)
                .setAudioSource(MediaRecorder.AudioSource.UNPROCESSED)
                .setAudioFormat(new AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(RECORD_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
                .setBufferSizeInBytes(Math.max(min, RECORD_RATE))
                .build();
        if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
            rec.release();
            emitError("the microphone could not be opened");
            return;
        }
        int total = (int) (RECORD_RATE * millis / 1000) * 2;
        byte[] pcm = new byte[total];
        try {
            rec.startRecording();
            JSONObject started = new JSONObject();
            started.put("type", "recording");
            started.put("rate", RECORD_RATE);
            emit(started);
            int read = 0;
            int error = 0;
            while (read < total) {
                int n = rec.read(pcm, read, Math.min(4096, total - read));
                if (n <= 0) {
                    error = n;
                    break;
                }
                read += n;
            }
            JSONObject o = new JSONObject();
            o.put("type", "audio");
            o.put("rate", RECORD_RATE);
            o.put("bytes", read);
            if (error != 0) {
                o.put("read_error", error);
            }
            o.put("pcm_b64", Base64.encodeToString(pcm, 0, read, Base64.NO_WRAP));
            emit(o);
        } finally {
            rec.stop();
            rec.release();
        }
    }

    // ------------------------------------------------------------- bluetooth

    /**
     * Scan for Bluetooth LE devices for `millis` and report how many answered
     * and how strongly. Names and addresses of other people's devices are
     * neither needed nor printed. An adapter that was off is switched on for
     * the scan and off again afterwards.
     */
    private static void bluetoothScan(long millis) throws Exception {
        Context ctx = shellContext();
        BluetoothManager bm = (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = bm == null ? null : bm.getAdapter();
        if (adapter == null) {
            // Some builds hand the service out only through the old static
            // accessor when the context is not an application's.
            adapter = BluetoothAdapter.getDefaultAdapter();
        }
        JSONObject o = new JSONObject();
        o.put("type", "bluetooth");
        if (adapter == null) {
            o.put("present", false);
            emit(o);
            return;
        }
        o.put("present", true);
        boolean wasOn = adapter.isEnabled();
        o.put("was_on", wasOn);
        if (!wasOn) {
            adapter.enable();
            for (int i = 0; i < 50 && adapter.getState() != BluetoothAdapter.STATE_ON; i++) {
                Thread.sleep(200);
            }
        }
        o.put("turned_on", adapter.getState() == BluetoothAdapter.STATE_ON);
        final Set<String> seen = new HashSet<>();
        final List<Integer> rssi = new ArrayList<>();
        BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
        if (scanner != null && adapter.isEnabled()) {
            ScanCallback callback = new ScanCallback() {
                @Override
                public void onScanResult(int type, ScanResult result) {
                    synchronized (seen) {
                        // The address only deduplicates; it never leaves.
                        if (seen.add(result.getDevice().getAddress())) {
                            rssi.add(result.getRssi());
                        }
                    }
                }
            };
            scanner.startScan(callback);
            Thread.sleep(millis);
            scanner.stopScan(callback);
        }
        synchronized (seen) {
            o.put("found", seen.size());
            JSONArray levels = new JSONArray();
            for (int r : rssi) {
                levels.put(r);
            }
            o.put("rssi", levels);
        }
        if (!wasOn) {
            adapter.disable();
        }
        emit(o);
    }

    // ---------------------------------------------------------------- camera

    /**
     * One still from every camera the system lists, at a small JPEG size,
     * with figures that tell a working sensor from a dead or covered one:
     * mean brightness, contrast (spread of brightness) and sharpness
     * (variance of a Laplacian). The JPEG goes to the PC for the operator to
     * look at; nothing is saved on the phone.
     */
    private static void captureCameras() throws Exception {
        CameraManager cm = cameraManager();
        HandlerThreadLite worker = new HandlerThreadLite();
        for (String id : cm.getCameraIdList()) {
            JSONObject o = new JSONObject();
            o.put("type", "camera");
            o.put("id", id);
            try {
                CameraCharacteristics ch = cm.getCameraCharacteristics(id);
                Integer facing = ch.get(CameraCharacteristics.LENS_FACING);
                o.put("facing", facing == null ? "unknown"
                        : facing == CameraCharacteristics.LENS_FACING_FRONT ? "front"
                        : facing == CameraCharacteristics.LENS_FACING_BACK ? "rear" : "external");
                byte[] jpeg = captureOne(cm, id, ch, worker.handler);
                if (jpeg == null) {
                    o.put("ok", false);
                    o.put("error", "no image within 8 seconds");
                } else {
                    o.put("ok", true);
                    describeImage(jpeg, o);
                }
            } catch (Throwable t) {
                o.put("ok", false);
                o.put("error", String.valueOf(t.getMessage()));
            }
            emit(o);
        }
        worker.quit();
    }

    private static byte[] captureOne(CameraManager cm, String id, CameraCharacteristics ch,
                                     Handler handler) throws Exception {
        StreamConfigurationMap map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.JPEG);
        if (sizes == null || sizes.length == 0) {
            return null;
        }
        Size pick = sizes[0];
        for (Size sz : sizes) {
            int px = sz.getWidth() * sz.getHeight();
            int best = pick.getWidth() * pick.getHeight();
            // Smallest size of at least ~0.3 MP: enough to judge, light to send.
            if (px >= 300_000 && (best < 300_000 || px < best)) {
                pick = sz;
            }
        }
        final ImageReader reader = ImageReader.newInstance(pick.getWidth(), pick.getHeight(),
                ImageFormat.JPEG, 2);
        final byte[][] out = new byte[1][];
        // Frames before this flag is set are dropped: they come while
        // auto-exposure is still converging and are usually far too dark.
        final boolean[] accepting = new boolean[1];
        final CountDownLatch done = new CountDownLatch(1);
        final CameraDevice[] device = new CameraDevice[1];
        reader.setOnImageAvailableListener(new ImageReader.OnImageAvailableListener() {
            @Override
            public void onImageAvailable(ImageReader r) {
                Image img = r.acquireLatestImage();
                if (img == null) {
                    return;
                }
                if (!accepting[0] || out[0] != null) {
                    img.close();
                    return;
                }
                ByteBuffer buf = img.getPlanes()[0].getBuffer();
                byte[] data = new byte[buf.remaining()];
                buf.get(data);
                img.close();
                out[0] = data;
                done.countDown();
            }
        }, handler);
        cm.openCamera(id, new CameraOpener(reader, done, device), handler);
        Thread.sleep(1500);
        accepting[0] = true;
        done.await(8, TimeUnit.SECONDS);
        if (device[0] != null) {
            device[0].close();
        }
        reader.close();
        return out[0];
    }

    /**
     * Opens the capture session once the camera is open. Named classes rather
     * than nested anonymous ones: d8 cannot convert an anonymous class
     * declared inside another anonymous class as javac 21 emits it.
     */
    private static final class CameraOpener extends CameraDevice.StateCallback {
        private final ImageReader reader;
        private final CountDownLatch done;
        private final CameraDevice[] device;

        CameraOpener(ImageReader reader, CountDownLatch done, CameraDevice[] device) {
            this.reader = reader;
            this.done = done;
            this.device = device;
        }

        @Override
        public void onOpened(CameraDevice cam) {
            device[0] = cam;
            try {
                Surface surface = reader.getSurface();
                cam.createCaptureSession(Arrays.asList(surface),
                        new SessionStarter(cam, surface, done), null);
            } catch (Throwable t) {
                done.countDown();
            }
        }

        @Override
        public void onDisconnected(CameraDevice cam) {
            done.countDown();
        }

        @Override
        public void onError(CameraDevice cam, int error) {
            done.countDown();
        }
    }

    private static final class SessionStarter extends CameraCaptureSession.StateCallback {
        private final CameraDevice cam;
        private final Surface surface;
        private final CountDownLatch done;

        SessionStarter(CameraDevice cam, Surface surface, CountDownLatch done) {
            this.cam = cam;
            this.surface = surface;
            this.done = done;
        }

        @Override
        public void onConfigured(CameraCaptureSession session) {
            try {
                CaptureRequest.Builder b = cam.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
                b.addTarget(surface);
                // A few frames let exposure settle before the one that is kept.
                session.setRepeatingRequest(b.build(), null, null);
            } catch (Throwable t) {
                done.countDown();
            }
        }

        @Override
        public void onConfigureFailed(CameraCaptureSession session) {
            done.countDown();
        }
    }

    private static void describeImage(byte[] jpeg, JSONObject o) throws Exception {
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inSampleSize = 2;
        Bitmap bmp = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, opts);
        if (bmp == null) {
            o.put("ok", false);
            o.put("error", "undecodable image");
            return;
        }
        int w = bmp.getWidth(), h = bmp.getHeight();
        int[] px = new int[w * h];
        bmp.getPixels(px, 0, w, 0, 0, w, h);
        double[] lum = new double[px.length];
        double sum = 0;
        for (int i = 0; i < px.length; i++) {
            int c = px[i];
            lum[i] = 0.299 * ((c >> 16) & 0xff) + 0.587 * ((c >> 8) & 0xff) + 0.114 * (c & 0xff);
            sum += lum[i];
        }
        double mean = sum / lum.length;
        double var = 0;
        for (double v : lum) {
            var += (v - mean) * (v - mean);
        }
        double lap = 0, lapSq = 0;
        int n = 0;
        for (int y = 1; y < h - 1; y++) {
            for (int x = 1; x < w - 1; x++) {
                double l = 4 * lum[y * w + x] - lum[y * w + x - 1] - lum[y * w + x + 1]
                        - lum[(y - 1) * w + x] - lum[(y + 1) * w + x];
                lap += l;
                lapSq += l * l;
                n++;
            }
        }
        o.put("width", w * 2);
        o.put("height", h * 2);
        o.put("brightness", Math.round(mean * 10) / 10.0);
        o.put("contrast", Math.round(Math.sqrt(var / lum.length) * 10) / 10.0);
        o.put("sharpness", n == 0 ? 0 : Math.round((lapSq / n - (lap / n) * (lap / n)) * 10) / 10.0);
        o.put("jpeg_b64", Base64.encodeToString(jpeg, Base64.NO_WRAP));
        bmp.recycle();
    }

    /** A background thread with a Looper, for camera callbacks. */
    private static final class HandlerThreadLite {
        final Handler handler;
        private final android.os.HandlerThread thread;

        HandlerThreadLite() {
            thread = new android.os.HandlerThread("pv-camera");
            thread.start();
            handler = new Handler(thread.getLooper());
        }

        void quit() {
            thread.quitSafely();
        }
    }

    private static int parseCount(String value) {
        try {
            return Math.max(1, Math.min(120, Integer.parseInt(value.trim())));
        } catch (NumberFormatException e) {
            return 1;
        }
    }

    private static void exit(int code) {
        System.out.flush();
        System.exit(code);
    }

    /** A duration argument in milliseconds, capped at ten seconds. */
    private static long parseMillis(String value) {
        try {
            return Math.max(0L, Math.min(10000L, Long.parseLong(value.trim())));
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    // ----------------------------------------------------------------- output

    private static synchronized void emit(JSONObject o) {
        OUT.println(o.toString());
        OUT.flush();
    }

    private static void emitError(String message) {
        try {
            JSONObject o = new JSONObject();
            o.put("type", "error");
            o.put("message", message);
            emit(o);
        } catch (Throwable ignored) {
        }
    }

    private static void emitFatal(Throwable t) {
        try {
            JSONObject o = new JSONObject();
            o.put("type", "fatal");
            o.put("message", String.valueOf(t.getMessage()));
            o.put("exception", t.getClass().getName());
            StringBuilder sb = new StringBuilder();
            StackTraceElement[] trace = t.getStackTrace();
            for (int i = 0; i < Math.min(6, trace.length); i++) {
                sb.append(trace[i].toString()).append('\n');
            }
            o.put("trace", sb.toString());
            emit(o);
        } catch (Throwable ignored) {
            ERR.println("fatal: " + t);
        }
    }

    private Agent() {
    }
}
