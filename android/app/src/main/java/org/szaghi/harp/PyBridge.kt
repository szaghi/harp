package org.szaghi.harp

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Single entry point to the embedded Python runtime (the shared harp core). */
object PyBridge {
    fun ensureStarted(context: Context) {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context.applicationContext))
        }
    }

    val py: Python
        get() = Python.getInstance()
}
