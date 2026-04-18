# Gifts that made this machine

This essay is the Commons wall in text. Every tool Scatter stands on
is named here, loudly. Scatter did not invent most of what it uses.
It arranged existing gifts into a shape that serves a particular
research posture. The gifts came first.

---

## The ground that holds all of it

**The Linux kernel** — Linus Torvalds, 1991, and roughly 25,000 contributors since. The reason this machine exists as something you can own all the way down is that a Finnish student in his dorm room decided a kernel should be free and kept saying yes. Scatter runs because the kernel runs.

**Ubuntu** — Mark Shuttleworth, Canonical, and the Ubuntu community since 2004. The specific shape of Linux-for-a-desktop that you open in the morning. Ubuntu 24.04 LTS (Noble Numbat) is Scatter's named substrate. When Scatter claims reproducibility, it is reproducibility on top of Ubuntu's long-term support commitment.

**GNU** — Richard Stallman and thousands of contributors, mostly invisible. `bash`, `coreutils`, `grep`, `sed`, `awk`, `tar` — the verbs of this machine. Every shell script Scatter writes assumes GNU's implementation of these. The research tradition of free software starts here.

**GNOME and GTK** — the GNOME project, the GTK team, and GIMP's early contributors who needed a widget toolkit before GNOME existed. Scatter's native windows are GTK windows. The familiar *feel* of a Linux desktop comes from decades of careful detail work by people whose names rarely leave commit logs.

**WebKit** — originally Apple's fork of KHTML (itself from the KDE project). The engine inside Safari, inside GNOME Web, and inside every PyGObject native window Scatter opens. A rendering engine you can embed without a subscription.

---

## The languages and runtimes

**Python** — Guido van Rossum and the Python Software Foundation. Scatter's entire server, substrate, CLI, and AI plumbing is Python standard library only (plus one or two carefully-chosen vetted packages declared in the README). Python's standard library is a gift of astonishing breadth — `urllib`, `json`, `http.server`, `pathlib`, `subprocess`, `uuid` — all right there, already reviewed by millions of eyes over decades.

**TypeScript and JavaScript** — Brendan Eich, Anders Hejlsberg, the TC39 committee, and the extended ecosystem. The prototype-era Scatter apps (Draft, Film, Music, Write) are TypeScript on top of Node. None of those would exist as running code without the browser-and-Node co-evolution.

**Next.js** — Guillermo Rauch and the Vercel team. The web framework the prototype apps run on. Scatter Film's timeline editor, Scatter Draft's split-pane script editor — both built inside Next.js's conventions.

**Node.js** — Ryan Dahl, the Node Foundation, now OpenJS. The runtime that makes JavaScript a plausible tool outside a browser.

---

## The AI that lives on this machine

**Ollama** — Jeffrey Morgan, Michael Chiang, the Ollama team. The local model runtime that makes `qwen2.5-coder:7b` something you can talk to without leaving your house. Ollama's `/api/generate` endpoint is the single point of trust for every local inference Scatter does.

**llama.cpp** — Georgi Gerganov. Ollama stands on `llama.cpp`, which is itself an achievement of brutal constraint: take a research artifact from a trillion-dollar company, compile it to run on a laptop.

**Qwen** — Alibaba's Qwen team. `qwen2.5-coder:7b` is what builds when you type "a red ball that bounces" in Scatter. A model you can inspect, weight-wise, and run locally, from a team that chose to release weights rather than hoard them.

**Llama** — Meta AI and the FAIR team. `llama3.2:3b` is Scatter's fast router — the small model that decides whether "hi scatter" is a greeting or a build request. The research that enables small-model chat-at-all was Meta's publication choice.

**Whisper (when installed)** — OpenAI's speech recognition model, released under an open license. Every `scatter ai transcribe` call that completes successfully is Whisper's work.

---

## The creative tools Scatter wraps

**LibreOffice** — The Document Foundation, descending from OpenOffice.org, descending from StarOffice. Decades of unpaid effort to preserve a word processor that is not Microsoft Word and not subject to a rental agreement. Scatter Writer is LibreOffice Writer, credited by name.

**GIMP** — The GNU Image Manipulation Program. Started by Spencer Kimball and Peter Mattis as undergraduates in 1995. Scatter Paint is GIMP, credited by name.

**Inkscape** — The Inkscape project, forked from Sodipodi, and the hundreds who kept it going. Scatter Vector is Inkscape, credited by name.

**Krita** — The Krita Foundation, descended from the KOffice project. A painting application by painters, for painters. Scatter Sketch is Krita, credited by name.

**Blender** — Ton Roosendaal and the Blender Foundation. Rescued from commercial death by a community fundraiser in 2002. Every 3D model, every rendered frame, every sculpt — Blender. Scatter Form is Blender, credited by name.

**Firefox** — Mozilla, descending from Netscape. The only major web browser that isn't financially chained to an advertising company. Scatter Browser is Firefox with a locked profile and a firejail bubble.

**Thunderbird** — also Mozilla. Email without a vendor. Scatter Mail is Thunderbird.

**OBS Studio** — the OBS Project and its contributors. Streaming and screencasting software that millions use without paying. Scatter Studio (the recording one, not the distilled app) is OBS.

**Audacity** — the Audacity Team, a decades-long project. Sound recording and editing for writers and musicians. Scatter Sound is Audacity.

---

## The small pieces that make it feel designed

**Inter** — Rasmus Andersson. A humanist sans-serif built for software UIs. If Scatter feels legible at small sizes, it's Inter.

**JetBrains Mono** — the JetBrains design team. A monospace face that's kind to long coding sessions. Scatter's default mono, across the GUI and the CLI.

**DM Sans** — Colophon Foundry. The prototype-era sans-serif; lives in the Studio theme as the alternative to Inter.

**Courier Prime** — John August and the Alan Dye team, redrawn for screenwriters. Scatter Draft's script-editor face (in the Studio theme).

**Open Props** — Adam Argyle. A zero-runtime CSS design token library. Influenced `tokens.css` even where Open Props isn't directly depended on.

**Lucide** — Timothy Miller and contributors, forked from Feather Icons. Clean line icons that render well at 16px.

**Motion One** — Matt Perry. A physics-based animation library that isn't Framer. A small gift for people who want spring motion without a 400KB dependency.

---

## The research traditions

**Free and Open Source Software** — Richard Stallman's GNU Manifesto, the BSD community, the Apache Foundation, the Linux Foundation, the GNOME Foundation, the Mozilla Foundation, the Document Foundation, the Python Software Foundation. The *idea* that software can be a commons — and the legal scaffolding (GPL, MIT, Apache 2.0, MPL) that lets that idea survive contact with corporate lawyers — is a gift.

**The UNIX tradition** — Dennis Ritchie, Ken Thompson, Brian Kernighan, and everyone who wrote C between 1969 and now. The idea that a machine should have small tools that compose.

**The Web tradition** — Tim Berners-Lee and the early W3C. That documents should be addressable, that hypertext should cross domains, that a page should render without an application installed.

**The Academic AI research tradition** — every paper whose preprint went up on arXiv before the model shipped. Attention Is All You Need. Language Models are Few-Shot Learners. The Chinchilla scaling paper. Release-to-the-literature-first is why any of this is reproducible at all.

---

## The one gift that is not software

**Ryann Murphy's craft.** Three produced plays. A tuba player's knowledge of arrangement. A screenwriter's knowledge of script breakdown. A columnist's knowledge of a sentence. This is not free software — it's work, over years, to earn the authority to say *most \[tool category\] is built by people who don't do the work, this is different*. Scatter Draft, Scatter Film, Scatter Music, Scatter Write are all gifts too — from the author to the user who might one day be a future version of the author.

---

## How this list ages

A few of these projects will not be here in ten years. One or two will become something different. A new kernel will emerge, someday; a new engine will replace WebKit; a new language will replace Python's role. Scatter will update this essay when that happens. The commitment is *name the current gifts loudly, then update the list when the gifts change.*

The wrong move is to claim the gifts as your own. Scatter refuses that move — every wrapped app shows the provenance in the Name and GenericName fields of the desktop entry; every AI call is tagged by model; every external call is audit-logged; and this essay exists.

The right move is to stand on shoulders, say whose shoulders they are, and build something that earns the weight.

---

*— The Scatter research project, 2026. This document is CC-BY 4.0.
Copy it, translate it, replace my name with your own for your own
attempt at the same shape. Please credit the gifts by name.*
