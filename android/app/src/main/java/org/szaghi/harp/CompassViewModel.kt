package org.szaghi.harp

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.LocationManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlin.math.abs

/**
 * A live azimuth/altitude correction toward the celestial pole.
 *
 * Positive [dAz] means the pole is to the RIGHT of where the reference now
 * points (turn the azimuth bolt that way); positive [dAlt] means it is HIGHER
 * (raise the altitude bolt). [onTarget] is true once both are within the
 * arcminute-ish tolerance the phone sensors can honour.
 */
data class Correction(val dAz: Float, val dAlt: Float) {
    val onTarget: Boolean get() = abs(dAz) < POLE_TOLERANCE_DEG && abs(dAlt) < POLE_TOLERANCE_DEG

    companion object {
        /** How close counts as aligned, degrees — the magnetometer floor, not a promise of arcminutes. */
        const val POLE_TOLERANCE_DEG = 0.5f
    }
}

/**
 * Sensor half of the polar-alignment compass tab.
 *
 * Pointing (true azimuth / altitude / roll) is read from the fused
 * ROTATION_VECTOR sensor and corrected magnetic->true with Android's
 * on-device World Magnetic Model (GeomagneticField, fed by the last GPS
 * fix) — exactly the source the horizon wizard uses. This is intentionally
 * a separate view model from [HorizonViewModel]: the compass has no vertex
 * list and no .hrz export, and the two have different screen lifecycles.
 * The sensor plumbing overlaps by design; a shared base class is a larger
 * refactor than this tab warrants.
 *
 * The celestial-pole target is a pure function of latitude, so it needs no
 * ephemeris: the pole sits due true north (az 0) in the northern hemisphere
 * or due true south (az 180) in the southern, at an altitude equal to the
 * observer's |latitude|. Polaris lies ~0.7 deg from the true north pole —
 * well inside the magnetometer's own 1-2 deg error, so it is drawn
 * coincident with the pole rather than pretending to sub-degree precision.
 *
 * GYRO HOLD ("INS mode"). The real alignment workflow is: aim the phone at
 * Polaris while clear of the mount (clean magnetometer), then walk the phone
 * toward the mount keeping it on Polaris — during which the mount's steel
 * corrupts the magnetometer and the fused heading swings off. The walk is a
 * translation, not a rotation, so the gyro sees almost no motion and drifts
 * negligibly (< 1 deg/hour -> ~0.001 deg over a 5 s walk). While locked we
 * therefore IGNORE the magnetometer and propagate the captured heading with
 * the gyro alone. Integration is done in the WORLD frame: the device-frame
 * angular-velocity vector is rotated by the current ROTATION_VECTOR matrix
 * and its world-vertical (Z) component is the true azimuth rate — exact at
 * any tilt, so holding Polaris high in the sky introduces no projection
 * error the way integrating raw device-Z would. The lock is manual,
 * calibration-gated, visibly indicated, and auto-released after
 * [HOLD_TIMEOUT_S] so a stale hold never survives a real re-aim.
 */
class CompassViewModel(app: Application) : AndroidViewModel(app), SensorEventListener {

    var azimuthTrue by mutableFloatStateOf(0f); private set
    var altitude by mutableFloatStateOf(0f); private set
    var roll by mutableFloatStateOf(0f); private set
    var declination by mutableFloatStateOf(0f); private set
    var sensorAccuracy by mutableIntStateOf(SensorManager.SENSOR_STATUS_UNRELIABLE); private set
    var latitude by mutableStateOf<Double?>(null); private set
    // Longitude is irrelevant to the coarse stage (the pole's azimuth and
    // altitude depend on latitude alone) but essential to the fine stage: the
    // reticle angle is driven by local sidereal time.
    var longitude by mutableStateOf<Double?>(null); private set
    var hasFix by mutableStateOf(false); private set

    // Gyro-hold state. When holding, [azimuthTrue] is the gyro-propagated
    // heading and the live magnetometer is ignored; [heldAtAccuracy] records
    // how good the compass was at lock time (garbage in -> frozen garbage).
    var holding by mutableStateOf(false); private set
    var holdElapsedS by mutableFloatStateOf(0f); private set
    var heldAtAccuracy by mutableIntStateOf(SensorManager.SENSOR_STATUS_UNRELIABLE); private set
    private var heldHeading = 0f
    private var holdStartNanos = 0L
    private var lastGyroNanos = 0L

    // ---- Fine (alignment-assistant) stage -----------------------------
    // ONE job: rough-align the mount in twilight, BEFORE Polaris is visible,
    // closely enough that Polaris lands in the polar scope's field when it
    // appears. Refinement afterwards is N.I.N.A. TPPA's job, not this tab's.
    //
    // That use case rules out any capture/calibration step: a reference taken
    // against a star you cannot yet see is impossible, and a reference taken
    // against nothing is meaningless. So the correction is always ABSOLUTE —
    // the computed pole minus where the phone points now. No modes, no state.
    //
    // The only thing that varies is how the phone sits on the mount, which is
    // a pure sensor-frame question answered by [flatMount], not by calibration.
    //
    // Accuracy: the magnetometer's 1-2 deg. A polar scope's field is ~5-8 deg,
    // so that is genuinely sufficient HERE — no hedging needed for this job.

    /**
     * How the phone is fixed to the mount.
     *
     * true  — FLAT: lying on the tube / a flat face, its long (top) edge along
     *         the polar axis. Verified against a constructed pose: the raw
     *         ROTATION_VECTOR matrix already reports exactly this direction,
     *         so no axis remap is applied.
     * false — BACK CAMERA: the back camera looks down the polar axis, which
     *         needs the (AXIS_X, AXIS_Z) remap.
     */
    var flatMount by mutableStateOf(true); private set

    // Refracted pole altitude from the core; falls back to bare |lat| offline.
    var poleAltitudeRefracted by mutableFloatStateOf(0f); private set
    var refractionReady by mutableStateOf(false); private set
    var alignError by mutableStateOf(""); private set

    // Atmospheric conditions for the refraction correction, mirrored from
    // Settings; a change re-solves the refracted altitude.
    private val settingsRepo = SettingsRepo(app)
    private var pressureHpa = 1010f
    private var tempC = 10f

    init {
        viewModelScope.launch {
            settingsRepo.flow.collect { s ->
                val changed = s.pressureHpa != pressureHpa || s.tempC != tempC
                pressureHpa = s.pressureHpa
                tempC = s.tempC
                if (changed && refractionReady) fetchRefractedAltitude()
            }
        }
    }

    fun chooseFlatMount(flat: Boolean) {
        flatMount = flat
    }

    /**
     * The pole altitude to aim at: refracted once the core has answered, the
     * bare geometric |lat| until then (the difference is ~1 arcmin, invisible
     * at this stage, so the fallback costs nothing).
     */
    val targetAltitude: Float
        get() = if (refractionReady) poleAltitudeRefracted else poleAltitude

    /**
     * Live correction from where the polar axis points now to the pole, or
     * null without a GPS fix (the pole altitude is the latitude).
     *
     * Positive dAz: the pole is to the right (east) — turn the azimuth bolt
     * that way. Positive dAlt: the pole is higher — raise the altitude bolt.
     */
    val correction: Correction?
        get() {
            if (!hasFix) return null
            var dAz = poleAzimuth - azimuthTrue
            if (dAz > 180f) dAz -= 360f
            if (dAz < -180f) dAz += 360f
            return Correction(dAz, targetAltitude - altitude)
        }

    /**
     * Refracted pole altitude from the Python core (needs only latitude, plus
     * pressure/temperature). Azimuth and the pole star's clock are not needed
     * by the assistant, so this asks for the one value that is not pure
     * geometry. Cheap; safe to re-run on entry or a settings change.
     */
    fun fetchRefractedAltitude() {
        val lat = latitude ?: return
        val lon = longitude ?: return
        viewModelScope.launch {
            val raw = withContext(Dispatchers.IO) {
                try {
                    val req = JSONObject().apply {
                        put("lat", lat)
                        put("lon", lon)
                        put("pressure_hpa", pressureHpa.toDouble())
                        put("temp_c", tempC.toDouble())
                    }
                    PyBridge.py.getModule("polar_bridge")
                        .callAttr("run_polar", req.toString()).toString()
                } catch (e: Exception) {
                    JSONObject().put("error", "${e.javaClass.simpleName}: ${e.message}").toString()
                }
            }
            try {
                val o = JSONObject(raw)
                if (o.has("error")) {
                    alignError = o.getString("error")
                    // keep the geometric fallback already in poleAltitudeRefracted
                } else {
                    alignError = ""
                    poleAltitudeRefracted = o.getDouble("pole_alt_refracted").toFloat()
                    refractionReady = true
                }
            } catch (e: Exception) {
                alignError = "bad alignment payload: ${e.message}"
            }
        }
    }

    private val sensorManager =
        app.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val rotationSensor: Sensor? =
        sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val gyroSensor: Sensor? =
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val rotation = FloatArray(9)
    private val remapped = FloatArray(9)
    private val orientation = FloatArray(3)
    // latest ROTATION_VECTOR matrix (device->world), for gyro world-frame projection
    private val worldFromDevice = FloatArray(9)

    fun startSensors() {
        rotationSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
        gyroSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
        refreshLocation()
    }

    fun stopSensors() = sensorManager.unregisterListener(this)

    /** True azimuth of the visible celestial pole: 0 = N (lat>=0), 180 = S. */
    val poleAzimuth: Float get() = if ((latitude ?: 0.0) >= 0.0) 0f else 180f

    /** Altitude of the celestial pole above the horizon = |latitude|. */
    val poleAltitude: Float get() = abs((latitude ?: 0.0)).toFloat()

    val northern: Boolean get() = (latitude ?: 0.0) >= 0.0

    /** A device with no gyroscope cannot offer the hold; the UI hides it. */
    val gyroAvailable: Boolean get() = gyroSensor != null

    /**
     * Latch the current fused heading and propagate it on the gyro alone.
     * Take this while the compass is calibrated and clear of the mount — the
     * hold preserves whatever heading it is given, it cannot improve a bad one.
     */
    fun lockHeading() {
        if (!gyroAvailable) return
        heldHeading = azimuthTrue
        heldAtAccuracy = sensorAccuracy
        holdStartNanos = 0L
        lastGyroNanos = 0L
        holdElapsedS = 0f
        holding = true
    }

    fun releaseHold() {
        holding = false
        holdElapsedS = 0f
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ROTATION_VECTOR -> onRotationVector(event)
            Sensor.TYPE_GYROSCOPE -> onGyro(event)
        }
    }

    private fun onRotationVector(event: SensorEvent) {
        SensorManager.getRotationMatrixFromVector(rotation, event.values)
        // Which device direction counts as "where this is pointing" depends on
        // how the phone is fixed to the mount. FLAT (long edge along the axis)
        // is what the raw matrix already reports, so it is used unremapped;
        // BACK CAMERA needs the (AXIS_X, AXIS_Z) remap. Both then share the
        // same altitude = -pitch convention below.
        if (flatMount) {
            System.arraycopy(rotation, 0, remapped, 0, 9)
        } else {
            SensorManager.remapCoordinateSystem(
                rotation, SensorManager.AXIS_X, SensorManager.AXIS_Z, remapped,
            )
        }
        // keep the device->world matrix for the gyro projection (unremapped:
        // rows are the world-frame components of the device x/y/z axes)
        System.arraycopy(rotation, 0, worldFromDevice, 0, 9)
        SensorManager.getOrientation(remapped, orientation)
        altitude = (-Math.toDegrees(orientation[1].toDouble())).toFloat()
        roll = Math.toDegrees(orientation[2].toDouble()).toFloat()
        // while holding, the magnetometer-derived heading is deliberately ignored
        if (!holding) {
            val azMag = (Math.toDegrees(orientation[0].toDouble()) + 360.0) % 360.0
            azimuthTrue = (((azMag + declination) % 360.0 + 360.0) % 360.0).toFloat()
        }
    }

    private fun onGyro(event: SensorEvent) {
        if (!holding) {
            lastGyroNanos = event.timestamp
            return
        }
        if (holdStartNanos == 0L) {
            holdStartNanos = event.timestamp
            lastGyroNanos = event.timestamp
            return
        }
        val dt = (event.timestamp - lastGyroNanos) / 1e9f
        lastGyroNanos = event.timestamp
        if (dt <= 0f || dt > 1f) return // skip gaps/backlog after (re)subscribe

        // rotate the device-frame rate into the world frame; the world-Z
        // component (row 2 of device->world dotted with the rate) is the
        // azimuth rate, exact at any tilt. rad/s -> deg.
        val wx = event.values[0]
        val wy = event.values[1]
        val wz = event.values[2]
        val worldZrate =
            worldFromDevice[6] * wx + worldFromDevice[7] * wy + worldFromDevice[8] * wz
        // world Z is up; a positive rotation about up is counter-clockwise,
        // i.e. DECREASING compass azimuth -> subtract.
        heldHeading =
            (((heldHeading - Math.toDegrees(worldZrate.toDouble()).toFloat() * dt) % 360f) + 360f) % 360f
        azimuthTrue = heldHeading

        holdElapsedS = (event.timestamp - holdStartNanos) / 1e9f
        if (holdElapsedS >= HOLD_TIMEOUT_S) releaseHold()
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
        if (sensor.type == Sensor.TYPE_ROTATION_VECTOR) sensorAccuracy = accuracy
    }

    private fun hasLocationPermission(): Boolean {
        val ctx = getApplication<Application>()
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    /** Cached last-known fix -> latitude + on-device declination. */
    fun refreshLocation() {
        if (!hasLocationPermission()) return
        val lm = getApplication<Application>()
            .getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val loc = try {
            lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
        } catch (_: SecurityException) {
            null
        } ?: return
        latitude = loc.latitude
        longitude = loc.longitude
        hasFix = true
        declination = GeomagneticField(
            loc.latitude.toFloat(),
            loc.longitude.toFloat(),
            (if (loc.hasAltitude()) loc.altitude else 0.0).toFloat(),
            System.currentTimeMillis(),
        ).declination
    }

    companion object {
        /** Auto-release the gyro hold after this long: drift stays sub-0.1 deg. */
        const val HOLD_TIMEOUT_S = 30f
    }
}
