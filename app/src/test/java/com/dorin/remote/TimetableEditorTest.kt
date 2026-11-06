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
        assertEquals(draft.copy(night = external.night), editor.reapply().draft)
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

    @Test fun reapplyMergesLocalMorningWithExternalNightAndSavesAgainstLatest() = runBlocking {
        val editor = TimetableEditor(initial, initial.copy(morning = "07:00"), external).reapply()
        val merged = external.copy(morning = "07:00")
        assertEquals(external, editor.baseline)
        assertEquals(merged, editor.draft)
        assertTrue(editor.dirty)
        assertFalse(editor.conflict)
        val calls = mutableListOf<String>()
        saveTimetable(editor, { path, body ->
            calls += path
            if (body == null) status(external) else {
                assertEquals(external, Timetable.from(body.getJSONObject("expectedConfig")))
                assertEquals(merged, Timetable.from(body))
                status(merged)
            }
        }, {})
        assertEquals(listOf("/v1/status", "/v1/config"), calls)
    }

    @Test fun reapplyOverlaysEachOfTheFiveChangedFieldsButPreservesEveryUntouchedField() {
        val latest = Timetable(false, "23:00", "09:00", "Europe/London", "30")
        val localChanges = listOf(
            initial.copy(enabled = false) to latest,
            initial.copy(night = "22:30") to latest.copy(night = "22:30"),
            initial.copy(morning = "07:00") to latest.copy(morning = "07:00"),
            initial.copy(timezone = "America/New_York") to latest.copy(timezone = "America/New_York"),
            initial.copy(pollSeconds = "5") to latest.copy(pollSeconds = "5"),
        )
        localChanges.forEach { (draft, expected) ->
            val editor = TimetableEditor(initial, draft, latest, rejected = true).reapply()
            assertEquals(expected, editor.draft)
            assertEquals(latest, editor.baseline)
            assertEquals(latest, editor.latest)
            assertEquals(expected != latest, editor.dirty)
            assertFalse(editor.conflict)
        }
        // Re-enable is also an explicit local change, not a truthy/default fallback.
        val disabled = initial.copy(enabled = false)
        assertTrue(TimetableEditor(disabled, initial, latest).reapply().draft.enabled)
    }

    @Test fun reapplyWithoutLocalChangesAdoptsLatestAndWithoutExternalChangesKeepsDraft() {
        val untouched = TimetableEditor(initial, initial, external).reapply()
        assertEquals(external, untouched.draft)
        assertEquals(external, untouched.baseline)
        assertFalse(untouched.dirty)
        val draft = initial.copy(morning = "07:00", enabled = false, pollSeconds = "3")
        val unchangedBaseline = TimetableEditor(initial, draft).reapply()
        assertEquals(initial, unchangedBaseline.baseline)
        assertEquals(draft, unchangedBaseline.draft)
        assertTrue(unchangedBaseline.dirty)
        assertFalse(unchangedBaseline.conflict)
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

    @Test fun serverRaceAfterFreshReadKeepsDraftAndReapplyOnlyOverridesEditedFields() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody(status(initial).toString()))
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"error":"Timetable changed on another device. Reload before saving."}"""))
        server.enqueue(MockResponse().setBody(status(external).toString()))
        server.start()
        try {
            val draft = initial.copy(morning = "08:00")
            var editor = TimetableEditor(initial, draft)
            val url = server.url("/").toString()
            try {
                saveTimetable(editor, { path, body -> ButlerClient.exchange(url, path, body) }, {
                    editor = editor.observe(Timetable.from(it.getJSONObject("config")))
                })
                fail("Expected atomic conflict after fresh read")
            } catch (_: TimetableConflict) {
                editor = editor.copy(rejected = true)
                editor = editor.observe(Timetable.from(ButlerClient.exchange(url, "/v1/status").getJSONObject("config")))
            }
            assertEquals(draft, editor.draft)
            assertTrue(editor.conflict)
            assertEquals(external, editor.latest)
            assertEquals(external.copy(morning = "08:00"), editor.reapply().draft)
            val requests = (0 until 3).map { server.takeRequest() }
            assertEquals(listOf("GET", "POST", "GET"), requests.map { it.method })
            assertEquals(listOf("/v1/status", "/v1/config", "/v1/status"), requests.map { it.path })
            val payload = JSONObject(requests[1].body.readUtf8())
            assertEquals(initial, Timetable.from(payload.getJSONObject("expectedConfig")))
            assertEquals(5, payload.getJSONObject("expectedConfig").length())
            assertFalse(payload.has("bulbs"))
        } finally { server.shutdown() }
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
