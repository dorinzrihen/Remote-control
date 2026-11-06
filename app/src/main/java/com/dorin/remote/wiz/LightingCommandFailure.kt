package com.dorin.remote.wiz

/** The manager answered successfully, but none of this room's bulbs acknowledged it. */
class BulbsDidNotAnswer(val room: String, details: String) : IllegalStateException(details)

/** A manager older than the rename endpoint answers 404 and has changed nothing. */
fun bulbRenameFailure(error: Exception): String =
    if (error is ButlerRequestRejected && error.code == 404) "Update the manager to rename bulbs" else lightingCommandFailure(error)

fun lightingCommandFailure(error: Exception): String = when (error) {
    is BulbsDidNotAnswer -> "Manager connected. ${error.room}: no bulbs answered. Check wall power and the bulb's connection."
    is ButlerRequestRejected -> "Lighting request rejected: ${error.message}"
    // A request/refresh failure does not establish that the manager is down or that
    // the command was never applied. Never encourage blind retries as if it was not sent.
    else -> "Lighting command not confirmed; outcome unknown: ${error.message}. Check manager status."
}
