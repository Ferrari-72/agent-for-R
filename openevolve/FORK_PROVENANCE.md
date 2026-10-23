# OpenEvolve fork provenance

This directory vendors OpenEvolve at upstream commit
`15441c04bc5906790b343e0ff103d33935c33c71`.

The initial local changes are preserved in
`../experiment/patches/openevolve.patch`. Subsequent changes add generic
iteration failure feedback, an iteration journal, and a process-safe HTTP
request budget. Tensor-network-specific code remains in `../experiment/`.

Keep upstream license notices. Record future upstream merges and local changes
in this file before changing the pinned base.
