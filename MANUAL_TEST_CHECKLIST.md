# Manual Test Checklist

## Setup

- Install dependencies with `pip install -r requirements.txt`.
- Grant Accessibility, Screen Recording, and Input Monitoring permissions.
- Start the app with `python run.py`.
- Confirm `logs/app.log` is created.

## Screen And Capture

- Open the Settings tab and confirm resolution, scale factor, display count, and primary display are shown.
- Add a rule and select a condition row.
- Move the mouse to a visible UI pixel and press `Shift+C`.
- Confirm X, Y, RGB values populate only that selected condition.
- Press `Shift+C` with no selected condition and confirm a warning appears in the status log.

## Rule Logic

- Create a single match condition with tolerance `0` and confirm it only fires on the exact color.
- Change to unmatch and confirm it fires when the pixel changes.
- Add an `AND` condition and confirm both must pass.
- Add an `OR` condition and confirm either can pass.

## Recording

- Start a recording named `manual_test`.
- Move the mouse, click, type one key, then stop recording.
- Confirm a JSON file appears in `recordings/`.
- Restart the app and confirm the recording appears in the dropdown.
- Delete or rename the recording file and click Refresh Recordings; confirm the dropdown updates.

## Actions

- Configure a rule to run a simple hotkey such as `shift+4`.
- Configure a rule to run a recorded sequence.
- Enable human-like playback and confirm playback is smooth.
- Disable human-like playback and confirm recorded timings are used.

## Scheduler And Safety

- Enable two rules and start automation.
- Confirm the UI remains responsive while rules are polling.
- Trigger both rules close together and confirm actions execute one after another.
- Test cooldown by keeping a condition true and confirming it does not fire continuously.
- Test `edge` mode by changing the pixel false to true.
- Test `once` mode by confirming the rule fires only once.
- Press `Shift+Esc` and confirm automation stops and status shows emergency stop.

## Error Handling

- Select a missing recording file in `rules/rules.json`, start automation, and confirm the error is logged without crashing.
- Set a coordinate outside the screen and confirm the rule reports an error without crashing.
- Temporarily remove Screen Recording permission and confirm capture/polling errors are shown.
