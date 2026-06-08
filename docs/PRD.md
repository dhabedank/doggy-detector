# Dog Detector Product Requirements

This document describes what Dog Detector is supposed to do, in plain language.
If the code and this document disagree, fix one of them. Do not leave them
telling different stories.

## The Short Version

Dog Detector is a small always-on system that runs at home on a Raspberry Pi.
It listens for barking, saves a short audio clip when barking happens, makes a
best guess about which known dog barked, and builds a report that can be handed
to animal control, an HOA, or another authority.

The product is for one specific problem:

> Two nearby dogs bark often. The owner needs a clear record of when it
> happened, how long it lasted, which dog it most likely was, and proof that
> the saved clips were not edited.

This is not a general smart speaker, security camera, cloud service, or legal
automation tool. It is a local evidence notebook for repeated barking.

## Who It Is For

The main user is the person running the device at home. They can install
software, edit a config file, and follow setup instructions, but they should not
need to babysit the system every day.

The second audience is the person reading the final report. That might be an
animal-control officer, HOA board member, neighbor mediator, or magistrate.
They will not care how the software works internally. They will care whether
the report is clear, believable, and easy to check.

## What Success Looks Like

After setup, the owner should be able to leave the device running for weeks.
When barking happens, they should see it appear in the dashboard within a few
seconds. If notifications are turned on, they should get a phone alert soon
after the barking stops.

After several days, the owner should be able to generate a PDF report that says:

- how many barking incidents happened,
- when each one started,
- how long each one lasted,
- which dog or yard the system thinks it came from,
- where the matching audio clip is,
- and the clip's fingerprint so the file can be checked later.

A reasonable report reader should be able to pick one incident, find the saved
audio file, run a standard file-fingerprint check on it, and confirm that the
clip matches the fingerprint printed in the report.

## What The Product Must Do

### Listen Continuously

The system must listen through a stereo microphone. Stereo matters because two
microphone channels help the system tell left from right.

The default recording rate should be high enough to compare the two channels
accurately. The system should keep a few seconds of recent audio in memory so
that a saved clip includes a little sound from before and after the bark.

If the microphone stops sending audio, the system must notice and show a health
problem. It should not quietly sit there looking healthy while recording
nothing.

### Detect Barking

The system must check each short audio window and decide whether it sounds like
dog vocalization. The owner can tune the sensitivity.

The default should catch normal barking without recording every unrelated
outdoor sound. If the owner gets too many false alarms, they can raise the
sensitivity setting. If quiet barks are missed, they can lower it.

### Turn Barking Into Incidents

Barking often comes in bursts. The product should group nearby barks into one
incident instead of creating a separate row for every single bark.

An incident starts after enough bark-like audio has been heard. It ends after
enough quiet audio has passed. Very short accidental hits should be ignored.

The owner can tune:

- how quickly an incident starts,
- how long quiet must last before it ends,
- how close two bursts can be before they get merged,
- and how short an incident can be before it is thrown away.

### Guess Which Dog Barked

Each saved incident must include a best-guess label and a confidence score.

The label should come from a few different clues:

- where the sound seemed to come from,
- whether it was louder on the left or right microphone,
- and, once the owner has labeled enough examples, whether the bark sounds like
  one of the known dogs.

The system must store a plain breakdown of those clues so the owner can inspect
why an incident was labeled a certain way.

The owner must be able to correct the label. Those corrections should help the
system get better over time.

### Save Evidence

Every real incident must be saved in the local database. The row must include:

- start and end time,
- duration,
- bark count,
- strongest and average bark score,
- direction summary if available,
- system label,
- owner-corrected label if any,
- whether the owner marked it as a false positive,
- notes or reason for flagging,
- audio clip path,
- audio clip fingerprint,
- and the saved clue breakdown used for labeling.

Every incident should have a matching saved audio clip. If writing the clip
fails, the database row must still be saved with an empty clip path so the
missing clip is visible instead of hidden.

Audio clips must be written once and left alone. The system stores a file
fingerprint when the clip is created. If someone edits or replaces the clip
later, the fingerprint will no longer match.

### Let The Owner Clean Up Mistakes

The dashboard must let the owner mark an incident as a false positive. The owner
may also write a short reason, such as "lawn mower" or "kids yelling."

The dashboard must let the owner override the dog label.

Reports should leave out false positives by default. False positives should not
be used as examples for learning bark identity.

### Produce A Report

The owner must be able to generate a PDF for any date range.

The report must include:

- the reporting period,
- when the report was generated,
- total incident count,
- a summary by dog or yard,
- an hour-by-hour activity chart,
- and a full incident log.

Each incident in the log must show the clip filename and the first part of the
clip fingerprint. The full fingerprint remains in the database.

Running the report again for the same date range and the same set of flagged
events should produce the same facts, even if the visual layout changes
slightly because of PDF rendering.

### Provide A Dashboard

The dashboard is a single web page served by the device.

It must show:

- whether the detector is running,
- the current bark score,
- a simple left/right direction display,
- the latest incidents,
- microphone and system health,
- and whether bark identity learning has enough examples yet.

The incident list must let the owner:

- play clips,
- filter rows,
- flag or unflag false positives,
- change labels,
- and inspect why the system chose a label.

The settings screen must let the owner edit the common tuning values from a
phone or laptop.

The live page should update automatically without needing manual refresh.

### Send Phone Notifications

If notifications are enabled, the system may send a push notification when an
incident ends. The owner can require a minimum score and minimum duration so
minor noises do not send alerts.

Notification failures must never stop recording, saving, or reporting.

The system should also send health notifications when it moves into a serious
problem state, such as a dead microphone. It should not spam the owner with the
same alert every few seconds.

### Show Health Clearly

The dashboard must show whether the sensor is healthy.

It should watch for:

- no audio arriving,
- a silent microphone channel,
- clipping,
- one microphone much weaker than the other,
- a microphone channel stuck off-center,
- low disk space,
- the Pi getting too hot,
- heavy system load,
- and whether the clock is synced.

The health state should be one of:

- `ok`,
- `warn`,
- `critical`,
- or `unknown`.

There must be a simple unauthenticated health URL for external uptime monitors.
It should return healthy when the system is okay or only warning, and unhealthy
when the system is critical or unknown.

### Help With Calibration

The calibration command must guide the owner through recording known sounds from
each dog or yard. It should then write direction zones into the config file.

Calibration does not need to be perfect. It needs to give the system a practical
left/right map that can be edited later.

### Work Remotely Without Opening The Home Router

The dashboard should work locally on the home network.

For remote access, the project supports two options:

**Option 1: Tailscale (recommended for simplicity)**

Tailscale creates a private network between the Pi and the owner's devices.
Setup requires one command on the Pi and installing the Tailscale app on the
phone or laptop. No account configuration beyond initial login. The Pi gets a
stable IP like `100.x.x.x` that works from anywhere.

Tailscale is the recommended option because:

- simpler setup (one command, no DNS or domain needed),
- automatic reconnection on network changes,
- works behind most firewalls without configuration,
- and the free tier is sufficient for personal use.

**Option 2: Cloudflare Tunnel**

Cloudflare Tunnel exposes the dashboard at a public URL like
`https://dog-detector.example.com`. This requires a Cloudflare account and
domain. The owner can put Cloudflare Access in front of the dashboard for
email-based login.

**Requirements for both options:**

- The tunnel service must be installed as a systemd unit.
- The tunnel must start automatically on boot.
- The tunnel must reconnect automatically if the connection drops.
- Tunnel credentials must persist across reboots.
- Local network access must still work if the tunnel provider is down.

## What The Product Must Not Do

Dog Detector should not:

- stream live audio to the cloud,
- act as a two-way speaker,
- contact animal control automatically,
- become a multi-user hosted service,
- try to recognize every possible animal or noise,
- or promise legal conclusions.

It records local evidence. The owner decides what to do with it.

## Privacy And Security

Audio stays on the device. Push notifications should include only event details,
not raw audio.

Every private dashboard request must require the dashboard token, except the
simple health check URL.

If no token is configured, the system should create one on first start and save
it. The dashboard must never return the real token in config responses.

The settings page must only allow normal tuning changes. It must not allow a
web request to change the dashboard token or database path.

The owner is responsible for local recording laws. The docs must make that
clear.

## Files And Data

All normal operating data should live in `config.yaml` and the `data/` folder.
Backing up those two things should back up the working system.

The main files are:

```text
config.yaml
data/
├── events.sqlite
├── clips/
│   └── YYYY-MM-DD/
│       └── HH-MM-SS_mmm.wav
└── reports/
    └── report-YYYY-MM-DD-to-YYYY-MM-DD.pdf
```

System service files live in standard locations:

```text
/etc/systemd/system/
├── dog-detector.service
└── tailscaled.service (or cloudflared.service)
```

The owner can choose how many days of data to keep. A value of `0` means keep
everything forever. When old data is pruned, both the database row and matching
clip should be removed.

## Reliability Rules

These rules matter more than polish:

1. If clip writing fails, the event row still gets saved.
2. A notification failure never blocks event saving.
3. A detector crash should be recoverable by the service manager.
4. The system must not pretend to be healthy when audio has stopped.
5. A saved clip should not be overwritten by a later clip.
6. The report must not include events the owner has flagged unless the owner
   explicitly asks for that.
7. The detector must start automatically when the Pi boots, with no manual
   intervention required.
8. The systemd service must be enabled and configured for automatic restart
   on failure with reasonable backoff.
9. The remote access tunnel must also start automatically on boot and reconnect
   if the connection drops.

## Hardware Assumptions

### Reference Hardware

The system is built for this specific setup:

- CanaKit Raspberry Pi 5 Starter Kit Turbine Black (8GB RAM, 128GB storage)
- Sony ECM-LV1 Compact Stereo Lavalier Microphone
- 3.5mm to USB-A audio adapter

This setup works but has a tradeoff: the ECM-LV1's two capsules are close
together (~1-2cm), which limits directional precision. For better left/right
separation, consider two separate omnidirectional microphones mounted 30-50cm
apart on a bar, connected through a stereo USB audio interface.

### Microphone Selection Notes

Many "omnidirectional USB microphones" are actually mono, even if they have
multiple capsules. When choosing a microphone, verify it outputs true stereo
(two distinct channels). The Sony ECM-LV1 is confirmed stereo.

For maximum directional accuracy, two separate microphones with wider spacing
will outperform any single-body stereo mic. Two cheap lavalier or clip-on
omnidirectional mics (under $20 each) mounted 30-50cm apart and connected
through a stereo USB adapter will give clearer left/right separation than any
single-body stereo microphone.

### USB Audio Considerations

USB audio adapters may appear as different device names across reboots. The
system must handle device discovery gracefully by:

- identifying the correct device by USB vendor/product ID, or
- allowing configuration by device name pattern, or
- auto-detecting the only available stereo USB input.

The config file should support specifying a device by name, pattern, or ID.
If the configured device is not found, the system must report a health error
rather than silently failing.

### Placement

The recommended placement is outside, protected from direct rain, with a clear
line of sound to both neighbor yards. For a shed setup, mount through the back
wall rather than around a corner. Corners bend and muffle sound enough to make
direction guesses worse.

The spacing between microphones (if using two separate mics) helps the system
tell left from right. Wider spacing gives clearer separation.

## Known Limits

The system can usually tell left from right. It cannot truly place a bark on a
map with only two microphones.

If both dogs bark at the same time, the system will usually label the louder or
clearer side. The confidence should be treated carefully.

If the microphone placement is poor, direction labels will be poor. Calibration
can help, but it cannot fully fix bad placement.

The general "dog" sound class can also react to whining or other dog noises.
The owner may choose to count only stronger bark-like classes if that matters.

Cloudflare Tunnel is optional and depends on a third party. If Cloudflare is
down, local access should still work.

## How We Judge The Product

The product is working well when:

- it stays running for weeks without attention,
- real barking appears quickly in the dashboard,
- clips are saved and fingerprint-checkable,
- false positives can be removed easily,
- corrected labels improve future labeling,
- reports are clear enough for a non-technical reader,
- and microphone problems are visible before days of evidence are lost.

The first version does not need to be scientifically perfect. It needs to be
clear, honest, local, inspectable, and useful.

## Roadmap

Already built or intended for the current product:

- continuous listening,
- bark detection,
- incident grouping,
- local clip saving,
- fingerprint-based clip checking,
- PDF reports,
- dashboard,
- false-positive flagging,
- push notifications,
- remote access docs,
- health monitoring,
- and multi-clue dog labeling.

Good next improvements:

- easier CSV export,
- clip thumbnails or small spectrogram views,
- scheduled weekly reports,
- quiet-hours rules,
- better handling of simultaneous barking,
- and stronger report signing if the evidence standard needs to rise.
