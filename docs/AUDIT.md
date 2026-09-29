# Public-copy validation record

The standalone public firmware build, 28 isolated HA tests and native C++ tests
passed when the source tree was prepared. Comparison of the public text with
known local passwords, tokens, io keys, SSIDs and personal identifiers found
no matches. Private-key, JWT, internal-address and excluded-file checks found
no issues. The sensitive-value list is not part of this report. UI labels and
a generic loopback address are not access credentials.

The English documentation update changes documentation, command-line messages
and HA localization only. The key-transfer guide contains protocol structure
and observed results, not actual keys, authentication witnesses or captures.
The acquisition receiver is not included; this limitation is stated explicitly.

At the time of the initial audit, the repository had no history or remote.
Build cache is outside the delivered tree. The public firmware was not deployed to live
devices. This record applies to the prepared copy; review future changes again.

After the English update, all 28 HA tests passed again. JSON localization files,
local documentation links and CLI help/validation were checked. The repeated
known-credential and personal-identifier comparison found no matches across
39 public files. English is the default; the Czech locale remains optional.
