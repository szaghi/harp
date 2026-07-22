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
import kotlin.math.abs

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
        // remap so the reported direction is where the back camera points
        SensorManager.remapCoordinateSystem(
            rotation, SensorManager.AXIS_X, SensorManager.AXIS_Z, remapped,
        )
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
