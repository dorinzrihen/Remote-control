package com.dorin.remote

import com.dorin.remote.net.YouTubeSearch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test

/** Live network test: Hebrew multi-word search must return results. */
class YouTubeSearchTest {
    @Test fun hebrewMultiWord() = runBlocking {
        repeat(3) {
            val r = YouTubeSearch.search("שיר של יום")
            println("results: ${r.size} first=${r.firstOrNull()?.title}")
            assertTrue(r.isNotEmpty())
        }
    }
    @Test fun english() = runBlocking {
        val r = YouTubeSearch.search("funny cats")
        assertTrue(r.isNotEmpty())
    }
}
