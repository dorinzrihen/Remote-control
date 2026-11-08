python := if os() == "windows" { "python" } else { "python3" }
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# Build, update and open Preview on the persistent, visible Pixel 8a (or stop/status).
emulator action="dev":
    @{{python}} tools/emulator.py {{action}}

# GUI end-to-end against simulated WiZ bulbs + the real manager on loopback (disposable emulator).
# e.g. `just mock-lights up`, `just mock-lights scenario`, `just mock-lights state`, `just mock-lights down`
mock-lights *args="scenario":
    @{{python}} tools/mock_e2e.py {{args}}
