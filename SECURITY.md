# Security Policy

## Supported versions

This project has not made a first release yet. Once released, only the
latest published version is supported with security fixes.

## Reporting a vulnerability

This repository is not yet published. Once it is published on GitHub,
report vulnerabilities privately through GitHub Security Advisories on the
repository rather than opening a public issue. A dedicated security contact
address will be added here before the first public release.

Please do not open a public issue for a suspected vulnerability before a
private reporting channel is available.

## What this tool does and does not protect against

ImageSet Guard performs local, read-only checks on image files. It is a
preflight tool, not a security boundary. Some of what follows describes
  behavior implemented in the discovery, image-inspection, and exact-hashing
  layers used by the public CLI. In particular:

- The dataset root path you pass in is trusted and may itself be a
  symbolic link or a Windows junction pointing at the real dataset — it
  is resolved to its real location before scanning starts. The
  "never follow a link" rule applies only to entries discovered *inside*
  that root, at any depth, never to the root argument itself. Both halves
  of this policy are implemented and tested today. (`DirEntry.is_symlink()`
  alone does not detect a junction; discovery checks for both.)
- Discovery never modifies, deletes, or moves files inside the scanned
  dataset — this is implemented and tested today.
- Operational failure messages (`ScanError.message`) are always one of a
  fixed set of registry strings — never the raw OS exception text, which
  can contain an absolute path or a username — this is implemented and
  tested today. The same applies to an entry name that cannot be safely
  represented in the report at all (e.g. one containing a control
  character): it is skipped and reported by code only, never by name.
- This is not a complete defense against a filesystem that changes while it is
  being scanned. Resolving the dataset root and then walking it is a
  check-then-use sequence like any other. Inspection rechecks that a
  candidate is a regular file, uses `O_NOFOLLOW` where the operating system
  provides it, compares file identity before decoding or hashing, and checks
  size and modification time again after use. Hashing also requires the file
  identity captured by inspection to still match, but these are
  best-effort mitigations rather than an atomic cross-platform guarantee.
  Scan a dataset that is stable and not being concurrently modified.
- Image inspection reduces, but does not eliminate, the risk of
  decompression-bomb-style resource exhaustion: it enforces a
  project-defined `max_pixels` limit in addition to Pillow's own built-in
  protection, but no Python image-decoding library can guarantee
  resistance to every current or future crafted input.
- Image inspection detects the *presence* of EXIF metadata and the
  top-level GPSInfo tag. It never opens the GPS IFD and never places EXIF
  values in a result. It does not strip or modify metadata, and does not
  decide whether its presence is actually sensitive in context.
- Image inspection compares file extensions against the format Pillow
  detects from file content, verifies file structure, and forces a pixel
  decode. This is more reliable
  than trusting the extension alone — but it will still rely on Pillow's
  decoders and cannot independently verify that a file is free of every
  form of malicious or malformed content.
- Decoder exception and warning text is not copied into findings or scan
  errors. Only fixed registry messages and non-sensitive boolean/count
  evidence are exposed.
- Exact-duplicate checking hashes eligible files with SHA-256 in bounded
  chunks. Digests are kept in internal grouping records and are never copied
  into findings or the public report contract. Findings identify a duplicate
  by safe relative path only. Hashing detects byte-identical files, not
  visually similar content, and does not establish ownership, license, or
  consent.
- It never sends any file, path, or metadata over a network.
- It does not detect malware embedded in image files beyond what causes the
  image itself to fail to decode. It is not an antivirus or content-security
  scanner.
- A generated report is written outside the dataset root and uses only
  paths relative to that root; it never includes absolute paths, usernames,
  timestamps, or the sensitive metadata values themselves. It can still
  reveal the relative directory and file names of a dataset if the report
  itself is shared — treat the report with the same care as the dataset's
  file listing.

This tool does not claim to be "secure" or "safe" in any absolute sense. It
narrows a specific, documented set of risks; it does not eliminate them.
