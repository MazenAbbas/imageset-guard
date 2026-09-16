"""Central registry of finding and scan-error codes.

Every code emitted anywhere in this project is declared here exactly once,
with exactly one default message. Modules build findings/scan errors by
importing a code constant and (usually) its default message from
``DEFAULT_MESSAGES`` -- they never write a code or a message as a bare
string literal. This is what keeps the code table stable and prevents the
same code from silently drifting into a second meaning.

Code namespaces:

- ``SPLITxxx`` -- dataset structure and file placement (category
  :attr:`imageset_guard.models.Category.STRUCTURE`).
- ``IMGxxx`` -- file-type integrity: the file is in the right place, but its
  format is not one v1 scans (category
  :attr:`imageset_guard.models.Category.INTEGRITY`).
- ``PRIVxxx`` -- privacy-relevant metadata presence (category
  :attr:`imageset_guard.models.Category.PRIVACY`). Values are never reported.
- ``DUPxxx`` -- exact-byte duplicates and cross-split leakage (category
  :attr:`imageset_guard.models.Category.LEAKAGE`). Digests are never reported.
- ``SYSxxx`` -- operational failures while scanning (permission, a path
  vanishing, or other OS errors). These become :class:`~imageset_guard.
  models.ScanError` entries, never :class:`~imageset_guard.models.Finding`.

Severity for most codes is fixed; a few (documented inline) depend on
context the caller supplies (e.g. an empty class directory is an error in
the required ``train`` split, but only a warning in an optional split) --
that is a difference in severity for the same underlying meaning, not a
second meaning for the code, so it does not need a second code.

This project has not made its first stable release (version is a
pre-release, e.g. ``0.1.0rc1``), so a code's *meaning* may still be
deliberately broadened before v1 ships
-- as long as it is a documented, intentional change and not a silent
drift. ``SPLIT_LINK_SKIPPED`` (``SPLIT010``) is the one example so far: it
originally meant "symbolic link", and was broadened to cover Windows
junctions/reparse mount points too, since both are "a filesystem entry
that redirects elsewhere and must never be followed" from a discovery
point of view -- see its docstring below.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# SPLITxxx: dataset structure and file placement
# ---------------------------------------------------------------------------

#: The required 'train' split does not exist. Always an error.
SPLIT_TRAIN_MISSING: Final = "SPLIT001"

#: 'train' exists but is not a directory. Always an error.
SPLIT_TRAIN_NOT_A_DIRECTORY: Final = "SPLIT002"

#: 'train' exists and is a directory, and its own direct listing was fully
#: enumerated, but it contains no class directories. Always an error. Never
#: emitted if 'train' itself could not be fully enumerated -- see
#: :func:`imageset_guard.discovery.discover`.
SPLIT_TRAIN_HAS_NO_CLASSES: Final = "SPLIT003"

#: A class directory's entire subtree was fully enumerated (no ScanError
#: anywhere in it) and contains no candidate image files. Error if the
#: class is in 'train'; warning if it is in an optional split ('validation'
#: or 'test'). Never emitted for a class whose subtree could not be fully
#: enumerated -- an incomplete count is not evidence of emptiness.
SPLIT_EMPTY_CLASS: Final = "SPLIT004"

#: A class exists in an optional split but not in 'train'. Always an error:
#: this split cannot be evaluated against classes the model never trains on.
#: Never emitted unless both splits' own direct listings were fully
#: enumerated -- see :func:`imageset_guard.discovery.discover`.
SPLIT_CLASS_MISSING_FROM_TRAIN: Final = "SPLIT005"

#: A class exists in 'train' but is missing from an optional split that is
#: otherwise present. Always a warning. Same completeness requirement as
#: ``SPLIT_CLASS_MISSING_FROM_TRAIN``.
SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT: Final = "SPLIT006"

#: An image-like file sits directly inside a split directory instead of
#: inside a class directory. Always a warning.
SPLIT_FILE_DIRECTLY_IN_SPLIT: Final = "SPLIT007"

#: An image-like file sits directly at the dataset root. Always a warning.
SPLIT_IMAGE_FILE_AT_DATASET_ROOT: Final = "SPLIT008"

#: A top-level directory is not 'train', 'validation', or 'test', so it was
#: not scanned at all. Always a warning.
SPLIT_UNRECOGNIZED_TOP_LEVEL_DIRECTORY: Final = "SPLIT009"

#: A filesystem entry that redirects elsewhere was found and was skipped --
#: never followed, even if it points inside the dataset. Covers both a
#: symbolic link and a Windows junction/mount-point reparse point (which
#: ``DirEntry.is_symlink()`` alone does not detect); ``evidence["link_type"]``
#: on the finding says which one. Always a warning.
SPLIT_LINK_SKIPPED: Final = "SPLIT010"

#: Two sibling names collide once normalized to the same Unicode
#: normalization form (NFC vs NFD); some filesystems treat them as the same
#: name and some do not. Always a warning; names are never rewritten.
SPLIT_UNICODE_NORMALIZATION_COLLISION: Final = "SPLIT011"

#: Two sibling names collide once case-folded; case-insensitive filesystems
#: (default on Windows and macOS) would treat them as the same name. Always
#: a warning; names are never rewritten.
SPLIT_CASE_FOLD_COLLISION: Final = "SPLIT012"

#: A path component is a reserved Windows device name (CON, PRN, AUX, NUL,
#: COM1-9, LPT1-9), with or without an extension, and with or without
#: trailing dots/spaces (Windows strips those before comparing). Always a
#: warning; names are never rewritten.
SPLIT_WINDOWS_RESERVED_NAME: Final = "SPLIT013"

#: A recognized optional split name ('validation' or 'test') exists but is
#: not a directory. Always an error: the user provided a recognized split
#: name with an invalid structure, which is worse than the split simply
#: being absent.
SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY: Final = "SPLIT014"

# ---------------------------------------------------------------------------
# IMGxxx: file-type integrity
# ---------------------------------------------------------------------------

#: A file inside a class directory has an extension outside the v1
#: candidate set (.jpg/.jpeg/.png/.webp, case-insensitive) and will not be
#: scanned in v1. Always a warning.
IMG_UNSUPPORTED_EXTENSION: Final = "IMG001"

#: A filesystem entry inside a class directory is not a regular file, a
#: directory, or a link (e.g. a socket, FIFO, or device file). It is
#: skipped and never opened. Always a warning.
IMG_NON_REGULAR_ENTRY: Final = "IMG002"

#: A candidate's bytes are not recognized as an image by Pillow. Always an
#: error: extension-only discovery found it, but there is no supported image
#: payload to train on.
IMG_UNIDENTIFIED_IMAGE: Final = "IMG003"

#: Pillow recognized the image header but could not verify or fully decode
#: the image. Always an error.
IMG_DECODE_FAILED: Final = "IMG004"

#: The image format detected from content does not match its filename
#: extension (or is outside JPEG/PNG/WebP). Always an error.
IMG_EXTENSION_FORMAT_MISMATCH: Final = "IMG005"

#: The image exceeds either the configured pixel limit or Pillow's own
#: decompression-bomb protection. Always an error.
IMG_PIXEL_LIMIT_EXCEEDED: Final = "IMG006"

#: The image contains multiple frames. v1 deliberately accepts static images
#: only, including for formats such as WebP and PNG that can be animated.
#: Always an error.
IMG_MULTIFRAME_UNSUPPORTED: Final = "IMG007"

#: Pillow completed the operation but emitted a non-decompression warning.
#: The warning text is deliberately discarded so it cannot leak decoder or
#: filesystem details. Always a warning.
IMG_DECODER_WARNING: Final = "IMG008"

# ---------------------------------------------------------------------------
# PRIVxxx: privacy metadata
# ---------------------------------------------------------------------------

#: The image contains EXIF metadata. Only presence is reported; values are
#: never copied into a finding. Always a warning.
PRIV_EXIF_PRESENT: Final = "PRIV001"

#: The image's top-level EXIF directory contains the GPSInfo tag. The GPS IFD
#: is never opened and coordinates are never read or reported. Always an error.
PRIV_GPS_PRESENT: Final = "PRIV002"

# ---------------------------------------------------------------------------
# DUPxxx: exact-byte duplicate and split leakage
# ---------------------------------------------------------------------------

#: Byte-identical files occur more than once in the same split and class.
#: Always a warning: this can unintentionally weight one sample repeatedly.
DUP_WITHIN_CLASS: Final = "DUP001"

#: Byte-identical files are assigned to different classes. Always an error:
#: identical input bytes carry conflicting labels.
DUP_ACROSS_CLASSES: Final = "DUP002"

#: Byte-identical files occur in different train/validation/test splits.
#: Always an error because evaluation leakage can inflate metrics.
DUP_ACROSS_SPLITS: Final = "DUP003"

# ---------------------------------------------------------------------------
# SYSxxx: operational failures during the scan
# ---------------------------------------------------------------------------

#: The scan lacked permission to access a path.
SYS_PERMISSION_DENIED: Final = "SYS001"

#: A path that discovery had already seen disappeared before it could be
#: examined further (a TOCTOU race, not a crash).
SYS_PATH_VANISHED: Final = "SYS002"

#: Any other OS-level failure while listing or inspecting a path.
SYS_STAT_OR_WALK_FAILURE: Final = "SYS003"

#: An entry's name cannot be represented safely in the canonical report
#: (e.g. it contains a control character, a backslash, or would look like
#: a Windows drive path). The entry itself is skipped -- not opened, not
#: named anywhere in any finding, message, or evidence -- and the split or
#: class it belongs to is treated as incompletely enumerated.
SYS_UNREPRESENTABLE_NAME: Final = "SYS004"

#: A candidate stopped naming the same stable regular file between checks,
#: or changed while it was being read. The partial result is discarded.
SYS_CANDIDATE_CHANGED: Final = "SYS005"

DEFAULT_MESSAGES: Final[dict[str, str]] = {
    SPLIT_TRAIN_MISSING: "The required 'train' split is missing.",
    SPLIT_TRAIN_NOT_A_DIRECTORY: "'train' exists but is not a directory.",
    SPLIT_TRAIN_HAS_NO_CLASSES: "'train' contains no class directories.",
    SPLIT_EMPTY_CLASS: "Class directory contains no candidate image files.",
    SPLIT_CLASS_MISSING_FROM_TRAIN: "Class exists in this split but not in 'train'.",
    SPLIT_CLASS_MISSING_FROM_OPTIONAL_SPLIT: (
        "Class exists in 'train' but is missing from this split."
    ),
    SPLIT_FILE_DIRECTLY_IN_SPLIT: (
        "Image-like file placed directly in the split directory, "
        "not inside a class directory."
    ),
    SPLIT_IMAGE_FILE_AT_DATASET_ROOT: "Image-like file placed directly at the dataset root.",
    SPLIT_UNRECOGNIZED_TOP_LEVEL_DIRECTORY: (
        "Top-level directory is not 'train', 'validation', or 'test'; it was not scanned."
    ),
    SPLIT_LINK_SKIPPED: (
        "A symbolic link or junction/reparse point was encountered; "
        "it was skipped and not followed."
    ),
    SPLIT_UNICODE_NORMALIZATION_COLLISION: (
        "Two names collide once normalized to the same Unicode form (NFC/NFD); "
        "this may break on some filesystems."
    ),
    SPLIT_CASE_FOLD_COLLISION: (
        "Two names collide once case-folded; this may break on case-insensitive filesystems."
    ),
    SPLIT_WINDOWS_RESERVED_NAME: (
        "Name is a reserved Windows device name; this may break on Windows."
    ),
    SPLIT_OPTIONAL_SPLIT_NOT_A_DIRECTORY: "Recognized split exists but is not a directory.",
    IMG_UNSUPPORTED_EXTENSION: "File has an unsupported extension and will not be scanned in v1.",
    IMG_NON_REGULAR_ENTRY: "Non-regular filesystem entry skipped; it was not opened.",
    IMG_UNIDENTIFIED_IMAGE: "File content is not recognized as an image.",
    IMG_DECODE_FAILED: "Image could not be verified and fully decoded.",
    IMG_EXTENSION_FORMAT_MISMATCH: (
        "Filename extension does not match the image format detected from content."
    ),
    IMG_PIXEL_LIMIT_EXCEEDED: "Image exceeds a configured or decoder safety limit.",
    IMG_MULTIFRAME_UNSUPPORTED: "Multi-frame or animated images are not supported in v1.",
    IMG_DECODER_WARNING: "Image decoder emitted a warning while reading this file.",
    PRIV_EXIF_PRESENT: "Image contains EXIF metadata.",
    PRIV_GPS_PRESENT: "Image contains GPS EXIF metadata.",
    DUP_WITHIN_CLASS: "Exact duplicate appears more than once in the same split and class.",
    DUP_ACROSS_CLASSES: "Exact duplicate is assigned to different classes.",
    DUP_ACROSS_SPLITS: "Exact duplicate appears in different dataset splits.",
    SYS_PERMISSION_DENIED: "Permission denied while accessing this path.",
    SYS_PATH_VANISHED: "Path disappeared during the scan.",
    SYS_STAT_OR_WALK_FAILURE: "Operating-system error while accessing this path.",
    SYS_UNREPRESENTABLE_NAME: (
        "Entry name cannot be represented safely in the report; the entry was skipped."
    ),
    SYS_CANDIDATE_CHANGED: "Candidate changed while it was being examined; result discarded.",
}
