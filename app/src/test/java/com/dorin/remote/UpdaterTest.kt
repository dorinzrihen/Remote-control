package com.dorin.remote

import com.dorin.remote.net.Updater
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdaterTest {
    @Test fun versionCompare() {
        assertTrue(Updater.isNewer("1.1", "1.0"))
        assertTrue(Updater.isNewer("1.10", "1.9"))
        assertTrue(Updater.isNewer("2.0", "1.99"))
        assertFalse(Updater.isNewer("1.0", "1.0"))
        assertFalse(Updater.isNewer("1.0", "1.1"))
        assertTrue(Updater.isNewer("1.1.1", "1.1"))
    }
}
