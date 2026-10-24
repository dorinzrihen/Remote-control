package com.dorin.remote.proto

import java.io.ByteArrayOutputStream

/**
 * Minimal protobuf wire-format encoder/decoder. Enough for the Android TV
 * pairing (polo.proto) and remote (remotemessage.proto) messages.
 */
class ProtoWriter {
    private val out = ByteArrayOutputStream()

    fun varint(field: Int, value: Long): ProtoWriter {
        tag(field, 0); writeVarint(value); return this
    }

    fun varint(field: Int, value: Int): ProtoWriter = varint(field, value.toLong())

    fun bool(field: Int, value: Boolean): ProtoWriter = varint(field, if (value) 1L else 0L)

    fun string(field: Int, value: String): ProtoWriter = bytes(field, value.toByteArray(Charsets.UTF_8))

    fun bytes(field: Int, value: ByteArray): ProtoWriter {
        tag(field, 2); writeVarint(value.size.toLong()); out.write(value); return this
    }

    fun message(field: Int, inner: ProtoWriter): ProtoWriter = bytes(field, inner.toByteArray())

    fun message(field: Int, build: ProtoWriter.() -> Unit): ProtoWriter {
        val w = ProtoWriter(); w.build(); return message(field, w)
    }

    fun toByteArray(): ByteArray = out.toByteArray()

    /** Length-prefixed frame as used on the wire by the Android TV remote protocol. */
    fun toFrame(): ByteArray {
        val body = toByteArray()
        val frame = ByteArrayOutputStream()
        writeVarintTo(frame, body.size.toLong())
        frame.write(body)
        return frame.toByteArray()
    }

    private fun tag(field: Int, wireType: Int) = writeVarint(((field shl 3) or wireType).toLong())

    private fun writeVarint(v: Long) = writeVarintTo(out, v)

    companion object {
        fun writeVarintTo(stream: ByteArrayOutputStream, value: Long) {
            var v = value
            while (true) {
                if ((v and 0x7FL.inv()) == 0L) {
                    stream.write(v.toInt()); return
                }
                stream.write(((v and 0x7F) or 0x80).toInt())
                v = v ushr 7
            }
        }
    }
}

/** Parsed protobuf message: field number -> list of raw values (Long for varint, ByteArray for length-delimited). */
class ProtoMessage(val fields: Map<Int, List<Any>>) {
    fun has(field: Int) = fields.containsKey(field)
    fun long(field: Int, default: Long = 0L): Long = (fields[field]?.lastOrNull() as? Long) ?: default
    fun int(field: Int, default: Int = 0): Int = long(field, default.toLong()).toInt()
    fun bool(field: Int): Boolean = long(field) != 0L
    fun bytes(field: Int): ByteArray? = fields[field]?.lastOrNull() as? ByteArray
    fun string(field: Int): String = bytes(field)?.toString(Charsets.UTF_8) ?: ""
    fun message(field: Int): ProtoMessage? = bytes(field)?.let { ProtoReader.parse(it) }
    fun messages(field: Int): List<ProtoMessage> =
        fields[field]?.mapNotNull { (it as? ByteArray)?.let(ProtoReader::parse) } ?: emptyList()
}

object ProtoReader {
    fun parse(data: ByteArray): ProtoMessage {
        val fields = HashMap<Int, MutableList<Any>>()
        var pos = 0
        while (pos < data.size) {
            val (tag, p1) = readVarint(data, pos); pos = p1
            val field = (tag ushr 3).toInt()
            when ((tag and 7).toInt()) {
                0 -> { val (v, p2) = readVarint(data, pos); pos = p2; fields.getOrPut(field) { mutableListOf() }.add(v) }
                1 -> { val v = readFixed(data, pos, 8); pos += 8; fields.getOrPut(field) { mutableListOf() }.add(v) }
                2 -> {
                    val (len, p2) = readVarint(data, pos); pos = p2
                    val end = pos + len.toInt()
                    if (end > data.size) throw IllegalArgumentException("truncated")
                    fields.getOrPut(field) { mutableListOf() }.add(data.copyOfRange(pos, end)); pos = end
                }
                5 -> { val v = readFixed(data, pos, 4); pos += 4; fields.getOrPut(field) { mutableListOf() }.add(v) }
                else -> throw IllegalArgumentException("unsupported wire type")
            }
        }
        return ProtoMessage(fields)
    }

    private fun readFixed(data: ByteArray, pos: Int, n: Int): Long {
        var v = 0L
        for (i in 0 until n) v = v or ((data[pos + i].toLong() and 0xFF) shl (8 * i))
        return v
    }

    /** Returns (value, newPos). Throws IndexOutOfBounds if incomplete. */
    fun readVarint(data: ByteArray, start: Int): Pair<Long, Int> {
        var pos = start
        var shift = 0
        var result = 0L
        while (true) {
            val b = data[pos].toInt(); pos++
            result = result or ((b and 0x7F).toLong() shl shift)
            if (b and 0x80 == 0) return result to pos
            shift += 7
            if (shift > 63) throw IllegalArgumentException("bad varint")
        }
    }
}
