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
    var declination by mutableFloatStateOf(0f); private set
    var sensorAccuracy by mutableIntStateOf(SensorManager.SENSOR_STATUS_UNRELIABLE); private set
    var latitude by mutableStateOf<Double?>(null); private set
    var longitude by mutableStateOf<Double?>(null); private set
    var elevation by mutableStateOf<Double?>(null); private set
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

    fun refreshLocation() {
        val ctx = getApplication<Application>()
        val fine = ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION)
        val coarse =
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (fine != PackageManager.PERMISSION_GRANTED &&
            coarse != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val loc = try {
            lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
        } catch (_: SecurityException) {
            null
        } ?: return
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
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
        if (sensor.type == Sensor.TYPE_ROTATION_VECTOR) sensorAccuracy = accuracy
    }

    fun addVertex() = vertices.add(Vertex(azimuthTrue, altitude.coerceIn(0f, 90f)))

    fun removeLast() {
        if (vertices.isNotEmpty()) vertices.removeAt(vertices.lastIndex)
    }

    /** Build the .hrz through the shared harp core; returns (file, problems). */
    fun exportHrz(): Pair<File, List<String>> {
        val points = vertices.map { listOf(it.azTrue.toDouble(), it.alt.toDouble()) }
        val json = PyBridge.py.getModule("wizard")
            .callAttr("make_hrz", points.toTypedArray())
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
