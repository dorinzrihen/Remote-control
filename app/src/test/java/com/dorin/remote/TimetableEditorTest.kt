package com.dorin.remote

import com.dorin.remote.wiz.*
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

class TimetableEditorTest {
    private val initial = Timetable(true, "21:00", "06:00", "Asia/Jerusalem", "1")
    private val external = initial.copy(night = "22:00")
    private fun status(t: Timetable) = JSONObject().put("config", t.json().put("bulbs", JSONArray()))

    @Test fun pristineEditorFollowsAnotherPhone() {
        assertEquals(external, TimetableEditor(initial).observe(external).draft)
    }

    @Test fun serverConflictStaysVisibleWhenRefreshingLatestStatusFails() {
        val editor = TimetableEditor(initial, initial.copy(morning = "08:00"), rejected = true)
        assertTrue(editor.conflict)
        assertTrue(editor.observe(initial).conflict)
        assertFalse(editor.reapply().conflict)
        assertEquals("08:00", editor.reapply().draft.morning)
    }

    @Test fun identicalPollsNeverResetTypedDraftAndExternalUpdatesPreserveIt() {
        val draft = initial.copy(morning = "0")
        var editor = TimetableEditor(initial, draft)
        repeat(5) { editor = editor.observe(Timetable.from(JSONObject(initial.json().toString()))) }
        assertEquals(draft, editor.draft)
        assertFalse(editor.conflict)
        editor = editor.observe(external)
        assertTrue(editor.conflict)
        assertEquals(draft, editor.draft)
        assertEquals(external, editor.reload().draft)
        assertEquals(draft, editor.reapply().draft)
        assertEquals(external, editor.reapply().baseline)
        assertFalse(editor.reapply().conflict)
    }

    @Test fun freshReadRefusesChangedScheduleAndKeepsDraft() = runBlocking {
        var editor = TimetableEditor(initial, initial.copy(morning = "08:00"))
        val calls = mutableListOf<String>()
        try {
            saveTimetable(editor, { path, _ -> calls += path; status(external) }, {
                editor = editor.observe(Timetable.from(it.getJSONObject("config")))
            })
            fail("Must not overwrite another phone")
        } catch (_: TimetableConflict) { }
        assertEquals(listOf("/v1/status"), calls)
        assertEquals("08:00", editor.draft.morning)
        assertTrue(editor.conflict)
    }

    @Test fun normalSaveContainsOnlyTimetableAndExpectedBaselineNotBulbs() = runBlocking {
        val draft = initial.copy(morning = "08:00")
        val calls = mutableListOf<String>()
        saveTimetable(TimetableEditor(initial, draft), { path, body ->
            calls += path
            if (body == null) status(initial).apply { getJSONObject("config").put("bulbs", JSONArray().put("changed")) }
            else {
                assertEquals(draft, Timetable.from(body))
                assertEquals(initial, Timetable.from(body.getJSONObject("expectedConfig")))
                assertFalse(body.has("bulbs"))
                assertFalse(body.getJSONObject("expectedConfig").has("bulbs"))
                assertEquals(5, body.getJSONObject("expectedConfig").length())
                status(draft)
            }
        }, {})
        assertEquals(listOf("/v1/status", "/v1/config"), calls)
        assertEquals(initial, Timetable.from(initial.json().apply { remove("pollSeconds") }))
    }

    @Test fun atomicServerConflictIsRecognizedAndDoesNotRetryPost() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"error":"Timetable changed on another device. Reload before saving."}"""))
        server.start()
        try {
            try {
                ButlerClient.exchange(server.url("/").toString(), "/v1/config", initial.json().put("expectedConfig", initial.json()))
                fail("Expected conflict")
            } catch (_: TimetableConflict) { }
            assertEquals(1, server.requestCount)
            assertEquals(initial, Timetable.from(JSONObject(server.takeRequest().body.readUtf8()).getJSONObject("expectedConfig")))
        } finally { server.shutdown() }
    }
}
