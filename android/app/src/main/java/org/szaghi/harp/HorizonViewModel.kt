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
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class Vertex(val azTrue: Float, val alt: Float)

/**
 * Sensor half of the horizon wizard.
 *
 * Pointing angles come from the ROTATION_VECTOR sensor (fused gyro +
 * accelerometer + magnetometer); the magnetic-to-true correction comes from
 * Android's built-in World Magnetic Model (GeomagneticField), fed by the
 * last known GPS fix — the manual NOAA-declination step of the desktop
 * workflow disappears entirely.
 *
 * AXIS CONVENTION (to verify on the first device run): after remapping the
 * rotation matrix with (AXIS_X, AXIS_Z), orientation[0] is the azimuth the
 * BACK CAMERA points at and -orientation[1] its elevation, for a phone held
 * upright in portrait. Sanity check on screen: camera at the horizon ->
 * alt = 0; at the zenith -> alt = +90. If a sign is off, it is one flip here.
 */
class HorizonViewModel(app: Application) : AndroidViewModel(app), SensorEventListener {

    var azimuthTrue by mutableFloatStateOf(0f); private set
    var altitude by mutableFloatStateOf(0f); private set
    var roll by mutableFloatStateOf(0f); private set
    var declination by mutableFloatStateOf(0f); private set
    var sensorAccuracy by mutableIntStateOf(SensorManager.SENSOR_STATUS_UNRELIABLE); private set
    var latitude by mutableStateOf<Double?>(null); private set
    var longitude by mutableStateOf<Double?>(null); private set
    var elevation by mutableStateOf<Double?>(null); private set
    var locationStatus by mutableStateOf(""); private set
    val vertices = mutableStateListOf<Vertex>()

    private val sensorManager =
        app.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val rotationSensor: Sensor? =
        sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val rotation = FloatArray(9)
    private val remapped = FloatArray(9)
    private val orientation = FloatArray(3)

    fun startSensors() {
        rotationSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
        refreshLocation()
    }

    fun stopSensors() = sensorManager.unregisterListener(this)

    private fun hasLocationPermission(): Boolean {
        val ctx = getApplication<Application>()
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun applyLocation(loc: android.location.Location) {
        latitude = loc.latitude
        longitude = loc.longitude
        elevation = if (loc.hasAltitude()) loc.altitude else null
        // on-device WMM: true azimuth = magnetic azimuth + declination
        declination = GeomagneticField(
            loc.latitude.toFloat(),
            loc.longitude.toFloat(),
            (if (loc.hasAltitude()) loc.altitude else 0.0).toFloat(),
            System.currentTimeMillis(),
        ).declination
    }

    /** Cached last-known fix, for instant startup values. */
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
        applyLocation(loc)
    }

    /** Active fix request (the GPS button): visible feedback, fresh position. */
    fun requestFix() {
        if (!hasLocationPermission()) {
            locationStatus = "location permission not granted"
            return
        }
        val ctx = getApplication<Application>()
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        locationStatus = "locating..."
        refreshLocation() // show the cached fix immediately while waiting
        try {
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                lm.getCurrentLocation(
                    LocationManager.GPS_PROVIDER,
                    null,
                    ContextCompat.getMainExecutor(ctx),
                ) { loc ->
                    if (loc != null) {
                        applyLocation(loc)
                        locationStatus = "GPS fix updated"
                    } else {
                        // indoors GPS often yields nothing: try the network provider
                        lm.getCurrentLocation(
                            LocationManager.NETWORK_PROVIDER,
                            null,
                            ContextCompat.getMainExecutor(ctx),
                        ) { netLoc ->
                            if (netLoc != null) {
                                applyLocation(netLoc)
                                locationStatus = "network fix (coarse)"
                            } else {
                                locationStatus = "no fix - need clear sky view"
                            }
                        }
                    }
                }
            } else {
                @Suppress("DEPRECATION")
                lm.requestSingleUpdate(
                    LocationManager.GPS_PROVIDER,
                    { loc ->
                        applyLocation(loc)
                        locationStatus = "GPS fix updated"
                    },
                    ctx.mainLooper,
                )
            }
        } catch (_: SecurityException) {
            locationStatus = "location permission not granted"
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return
        SensorManager.getRotationMatrixFromVector(rotation, event.values)
        // remap so the reported direction is where the back camera points
        SensorManager.remapCoordinateSystem(
            rotation, SensorManager.AXIS_X, SensorManager.AXIS_Z, remapped,
        )
        SensorManager.getOrientation(remapped, orientation)
        val azMag = (Math.toDegrees(orientation[0].toDouble()) + 360.0) % 360.0
        azimuthTrue = (((azMag + declination) % 360.0 + 360.0) % 360.0).toFloat()
        altitude = (-Math.toDegrees(orientation[1].toDouble())).toFloat()
        roll = Math.toDegrees(orientation[2].toDouble()).toFloat()
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
        if (sensor.type == Sensor.TYPE_ROTATION_VECTOR) sensorAccuracy = accuracy
    }

    fun addVertex() = vertices.add(Vertex(azimuthTrue, altitude.coerceIn(0f, 90f)))

    /** Mark the current azimuth as fully blocked (wall/building edge): alt 90. */
    fun addWallEdge() = vertices.add(Vertex(azimuthTrue, 90f))

    fun removeLast() {
        if (vertices.isNotEmpty()) vertices.removeAt(vertices.lastIndex)
    }

    /** Build the .hrz through the shared harp core; returns (file, problems). */
    fun exportHrz(): Pair<File, List<String>> {
        // JSON across the bridge: Java collections arrive in Python as
        // opaque proxies that tuple unpacking cannot iterate
        val points = JSONArray().apply {
            vertices.forEach {
                put(JSONArray().apply { put(it.azTrue.toDouble()); put(it.alt.toDouble()) })
            }
        }
        val json = PyBridge.py.getModule("wizard")
            .callAttr("make_hrz", points.toString())
            .toString()
        val parsed = JSONObject(json)
        val problems = buildList {
            val arr = parsed.getJSONArray("problems")
            for (i in 0 until arr.length()) add(arr.getString(i))
        }
        val dir = File(getApplication<Application>().cacheDir, "exports").apply { mkdirs() }
        val file = File(dir, "horizon.hrz")
        file.writeText(parsed.getString("hrz"))
        return file to problems
    }
}
