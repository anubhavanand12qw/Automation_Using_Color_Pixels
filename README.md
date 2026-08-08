# Automation Using Color Pixels

A macOS desktop automation app that watches **screen pixel colors** and triggers mouse and keyboard actions when your conditions match. Build rules from one or more RGB checks (with tolerance), combine them with `AND` / `OR` logic, and fire recorded sequences, hotkeys, text input, or direct clicks — including pointer-relative and Retina-safe coordinate handling.

Use it for game helpers, repetitive UI workflows, or any task where “when this pixel looks like X, do Y” is enough.

## Features

- Capture the current mouse coordinate and RGB color with `Shift+C`.
- Capture pointer-relative offsets with `Shift+O` then `Shift+L`.
- Start automation with `Shift+Delete`.
- Start recording with `Shift+R` and stop recording with `Shift+S`.
- Build multiple pixel conditions per rule with left-to-right `AND` / `OR` logic.
- Let a condition follow the current mouse pointer and match the pixel under the cursor.
- Use match or unmatch color checks with per-channel tolerance.
- Record mouse movement, clicks, scrolls, key presses, key releases, and event delays.
- Use a native Quartz event tap for recording on macOS to avoid extra `pynput` listener crashes.
- Save recordings under `recordings/` and reload them after restart.
- Execute simple hotkeys such as `shift+4`, `cmd+c`, `cmd+v`, and `ctrl+option+a`.
- Execute direct left-click and right-click actions.
- Monitor active rules in parallel without freezing the GUI.
- Serialize recorded sequence playback through one recording lock while allowing direct clicks, hotkeys, key presses, and text actions to run in parallel.
- Enable simple human-like timing for click and key press/release events.
- Configure polling interval, cooldown, repeat mode, edge trigger, or trigger once.
- Emergency stop with `Shift+Esc`.

## macOS Permissions

Open **System Settings > Privacy & Security** and grant the terminal or Python launcher you use:

- **Accessibility**: required to move the mouse, click, press keys, and execute hotkeys.
- **Screen Recording**: required to read pixel colors from the screen.
- **Input Monitoring**: required for global hotkeys and full input recording.

After changing permissions, restart the app. macOS may require restarting the terminal as well.

## Installation

```bash
git clone https://github.com/anubhavanand12qw/Automation_Using_Color_Pixels.git
cd Automation_Using_Color_Pixels
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python run.py
```

## Create a Rule

1. Click **Add Rule**.
2. Select the new rule in the rule list.
3. Click **Add AND Condition** or **Add OR Condition**.
4. Select the condition row.
5. Move the mouse to the target pixel.
6. Press `Shift+C`.
7. The app fills X, Y, RGB, screen info, and timestamp for the selected condition.
8. Choose **Match Color** or **Unmatch Color** and set tolerance.
9. Configure polling interval, cooldown, trigger mode, and human-like mode.

For click rules that must react as fast as possible, set **Polling interval** to `1`, `2`, or `5` ms and reduce **Cooldown** to the smallest value that is safe for your target. Lower intervals check the pixel more often and react faster, with higher CPU use.

`Shift+C` updates only the currently selected condition row. If no condition is selected, the status log shows a warning.

Enable **Use Pointer** on a condition when you want the rule to continuously sample near the current mouse pointer instead of a fixed X/Y coordinate. In this mode, X and Y become offsets from the current pointer: `0,0` samples directly under the pointer, `10,-5` samples 10 px right and 5 px above it. If the offset points outside the screen, that condition evaluates false instead of crashing. If that rule triggers a recorded sequence, the rule worker is busy until playback finishes, then it resumes pointer listening.

For pointer-relative capture, select a condition with **Use Pointer** checked, move the cursor to the reference point, and press `Shift+O`. Then move the cursor to the pixel you want to watch and press `Shift+L`. The app writes the target RGB plus the offset from the first point into X and Y. Example: if `Shift+O` is captured at `500,500` and `Shift+L` is captured at `512,493`, the condition gets `X=12`, `Y=-7`, and the RGB from `512,493`.

## Actions

## Automation Hotkeys

- `Shift+Delete`: start automation.
- `Shift+Esc`: emergency stop automation.

On MacBook keyboards, the key labeled **delete** may be reported as Backspace internally; the app registers both forms for the same start shortcut.

### Recorded Sequence

1. Open the **Recorder** tab.
2. Enter a recording name.
3. Click **Start Recording** or press `Shift+R`.
4. Perform the mouse and keyboard steps.
5. Click **Stop Recording** or press `Shift+S`.
6. Return to **Rule Editor**.
7. Set **Action Type** to **Select Recorded Sequence**.
8. Pick the saved JSON file from the dropdown.

Recordings are saved in `recordings/`. Click **Refresh Recordings** if files were added outside the app. Click **Delete Recording** to remove the selected recording file; the app clears any rules that referenced the deleted file.

`Shift+R` switches to the Recorder tab and starts recording after a short delay so the shortcut release is not captured as part of the recording. `Shift+S` stops and saves the active recording; the app trims the trailing stop shortcut events from the saved recording.

If automation is running when recording starts, the app stops automation first. This avoids recording the app's own playback and keeps macOS input hooks stable.

Human-like mode is timing-only. It keeps mouse movement coordinates and paths exactly as recorded, and only adds small random timing variation around mouse press/release and keyboard press/release events.

Enable **Play recording relative to current pointer** when you want recorded mouse coordinates to replay as offsets from the pointer location at trigger time. The first mouse-position event in the recording becomes the recording anchor; later mouse moves, clicks, and scroll positions are shifted by the same delta. Keyboard events are not changed.

Use **Playback speed** to run a selected recording faster or slower. `1.0x` preserves recorded timing, values below `1.0x` slow playback, and values above `1.0x` speed it up. The UI includes very slow options down to `0.05x` and fast options up to `20.0x`.

### Key, Hotkey, Or Text

Set **Action Type** to **Press Key / Hotkey / Type Text** and enter a hotkey, a single key, or plain text.

Supported modifiers:

- `shift`
- `cmd` or `command`
- `ctrl` or `control`
- `option` or `alt`
- `fn` when supported by `pynput` on the current macOS version

Examples:

```text
Anubhav
a
enter
shift+4
cmd+c
cmd+v
ctrl+option+a
```

Inputs without `+` are typed as text unless they match a known key name such as `enter`, `tab`, `space`, `esc`, `backspace`, or an arrow key.

### Mouse Click

Set **Action Type** to **Mouse Left Click** or **Mouse Right Click** to click at the pointer location captured in the same polling snapshot that matched the rule. Direct click actions use a priority mouse lane and a very short down/up click window, so recorded playback yields between mouse steps instead of delaying the click behind normal movement.

## Trigger Modes

- `repeat`: fire whenever the condition is true and cooldown has elapsed.
- `edge`: fire only when the rule changes from false to true.
- `once`: fire once per automation session.

## Concurrency Model

The scheduler starts one worker thread per enabled rule. Pixel reads happen independently, so many rules can be monitored at the same time. Recorded sequence playback is protected by a single recording lock, so two recordings do not play over each other. Direct clicks, hotkeys, key presses, and text actions are not blocked by that recording lock, so they can run while a recording is playing. Mouse operations also share a priority operation lane: playback yields between mouse steps, and direct clicks take priority for a fast move/down/up click window.

Pointer-relative click rules get an additional fast path: recorded playback publishes mouse coordinates after playback moves, and pointer-based conditions evaluate against the newest playback coordinate plus the live cursor fallback. The scheduler intentionally drops older queued playback positions so click rules do not fall behind and act on stale coordinates. On macOS, direct click actions use native Quartz click events when available, falling back to `pyautogui` if needed.

The GUI thread never performs rule polling or playback. Worker events and log messages are delivered through thread-safe queues and drained by a Qt timer.

## Retina Coordinate Handling

Cursor positions are treated as macOS logical coordinates. The screen capture layer compares logical desktop size with physical screenshot dimensions from `mss` and derives a scale factor, commonly `2.0` on Retina displays. Pixel sampling multiplies logical coordinates by that scale before reading the physical screenshot pixel, keeping captured cursor coordinates and RGB reads aligned.

Current screen resolution, scale factor, display count, and primary display details are shown in the **Settings** tab.

## Persistence

- Rules: `rules/rules.json`
- Recordings: `recordings/*.json`
- Logs: `logs/app.log`
- Config: `config/config.json`

Rules and recordings are loaded automatically when the app starts.

## Tests

```bash
source .venv/bin/activate
pytest
```

## Troubleshooting

- If hotkeys do not fire, grant **Input Monitoring** and restart the terminal/app.
- If pixel capture fails or returns wrong colors, grant **Screen Recording** and restart the app.
- If playback does nothing, grant **Accessibility**.
- If a recording is missing or invalid, the rule logs the error and automation continues.
- If a condition remains true and fires too often, increase cooldown or use `edge` mode.
- If your display configuration changes, restart automation or reopen the app to refresh scale detection.

## Known Limitations

- Condition expressions are evaluated left-to-right in version 1.
- Nested condition groups are not implemented yet, but the JSON structure leaves room for them.
- Multi-monitor detection is shown, but pixel capture is optimized for the primary display.
- The app does not overwrite recordings; new filenames include timestamps.
- macOS permission checks are best-effort because Input Monitoring has no reliable public preflight API.
