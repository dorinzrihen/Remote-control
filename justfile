python := if os() == "windows" { "python" } else { "python3" }
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# Build, update and open Preview on the persistent, visible Pixel 8a (or stop/status).
emulator action="dev":
    @{{python}} tools/emulator.py {{action}}
