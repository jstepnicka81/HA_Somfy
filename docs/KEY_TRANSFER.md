# Getting an io system key: observed transfer workflow

This guide documents the owner-authorized TaHoma Switch / TTGO experiment
behind the project. It does not include an installation key, a captured wrapped
key, an authentication witness, a private radio address, or the original
experimental transfer receiver. The public gateway supports importing an
existing key over USB; it does not implement the transfer steps below.

## What was established

- Passive reception was useful for identifying traffic, but did not trigger
  the tested TaHoma **Transfer → Remote control** workflow.
- An active, addressed CMD `0x38` request during the user-opened send window
  elicited CMD `0x32` carrying a 16-byte wrapped key.
- For this pull transaction, the working transcript was `0x38 || request_nonce`.
  Using only `0x31`, as in a push-flow example, produced the wrong candidate.
- The candidate matched a MAC from a separate authenticated exchange in the
  same installation, was stored in NVS, survived reboot, and successfully
  authenticated direct commands and status requests to multiple motors.
- We did not capture a confirmed final CMD `0x3d` acknowledgement in the
  transfer handshake itself. Do not describe that entire handshake as verified.

## Prerequisites

Use your own installation, owner access to TaHoma's key-transfer function,
and an io-capable diagnostic receiver that explicitly supports the addressed
transfer request and verification. The experimental receiver used an ESP32
with an SX1276 in FSK mode. An ordinary LoRa packet receiver is not equivalent.

Use a spare board where possible. Back up an existing board's entire flash
privately before changing firmware. Its NVS can contain Wi-Fi credentials,
API tokens and the io system key. Do not reset a motor, generate a new household
key or replace a working key just to follow this experiment.

Find the TaHoma **radio address** from a valid packet captured while you issue
an ordinary command in your own installation. Read source/destination fields;
do not confuse the radio address with its IP address, gateway PIN, device URL
or serial number. Give the diagnostic receiver its own distinct radio identity.

## Step-by-step transfer

1. Capture a normal authenticated exchange with a motor you own. Preserve the
   exact command plus payload, the associated six-byte CMD `0x3c` challenge,
   and the following six-byte CMD `0x3d` MAC. Correlate source, destination and
   timing, rather than combining unrelated packets. Store the capture privately.
2. Open the key-send/transfer workflow in the TaHoma app. The wording observed
   in our test was **Transfer → Remote control**. Menu layout may differ;
   no universal current UI path has been verified for every app version.
3. Arm the diagnostic receiver for a bounded operation while this window is
   open. Send an addressed CMD `0x38` to your gateway with a fresh six-byte
   nonce. Keep the exact nonce used by this request.
4. Receive CMD `0x32` containing the 16-byte wrapped key. Require a valid packet
   CRC and the expected source/destination. Wrapped bytes and the request nonce
   must come from the same transfer attempt.
5. Unwrap the candidate using the transfer protocol below. Keep it private and
   do not accept it merely because it has the correct length.
6. Check the candidate against the independent command/challenge/MAC from
   step 1. If verification fails, stop and diagnose the transcript, packet
   association and flow type; do not overwrite an already verified key.
7. Persist the verified key, reboot the receiver and check that it remains
   stored. Test an authenticated status request first. The original experiment
   also checked supervised direct movements and returned actual positions.
8. Provision operational gateways using the USB import described in
   [SETUP.md](SETUP.md). Preserve each ESP's own identity and existing NVS.

The historical diagnostic commands were named `P` (receive a push), `K`
(request a transfer), and `X` (private USB export). They are historical labels,
**not commands to run against the public gateway**. This release intentionally
excludes that diagnostic firmware and its installation-specific verification
material. It also excludes the public protocol transfer-key constant; an
external compatible transfer implementation must supply its own protocol code.

## Transcript details

For the observed pull path:

```text
request command:    0x38
request payload:    fresh nonce, 6 bytes
response command:   0x32
response payload:   wrapped key, 16 bytes
unwrap transcript:  0x38 || request_nonce
candidate:          wrapped_key XOR AES128(transfer_key, IV(transcript, request_nonce))
```

The protocol transfer key is a shared protocol constant, not the unique io
system key of a household. Knowing that constant alone does not provide this
project with an installation's key. No hexadecimal key values are provided here.

The public `cryptBlock()` implementation in
`ttgo-io-gateway/src/io_crypto.h` documents the block construction used for
normal authentication: first eight command/transcript bytes with `0x55`
padding, a two-byte transcript checksum, then the six-byte nonce. The function
processes all transcript bytes for the checksum, even beyond the first eight.
For independent validation, encrypt that block with the **candidate system key**
and compare its first six bytes with the recorded MAC. The transfer unwrapping
step and the normal-command verification step use different keys and transcripts.

A status query in this implementation uses command `0x03` and payload
`03 00 00`, so its authentication transcript is `03 03 00 00`. Do not reuse
another installation's challenge/MAC or publish your own as an example.

## Failure cases from development

| Symptom | What to check |
|---|---|
| Listening sees no key transfer | The tested UI waited for an active request; listening alone was insufficient. |
| App says the key was sent, but the receiver has no usable key | Verify the radio exchange, candidate MAC and persistence separately. |
| Candidate verification fails | Check pull versus push transcript and that nonce/wrapped key belong together. |
| Key disappears after reflashing | A candidate held only in RAM is lost; persist a verified key and preserve NVS. |
| Wrapped bytes were saved successfully | This is diagnostic evidence, not proof of a verified system key. |
| One motor works but another does not | Investigate reachability, device type and key membership; a timeout alone proves none of them. |

Never include raw transfer captures, flash dumps, io keys or tokens in public
issues. The original installation's values were deliberately removed from this
repository. If you lack a verified key and a compatible transfer receiver,
first-time key onboarding remains an external requirement of this release.
