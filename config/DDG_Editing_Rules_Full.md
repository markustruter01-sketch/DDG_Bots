# DDG EDITING RULES - FULL EXPORT (24 Nov 2026)

## PART 1: DDG Video Editing Playbook
---
name: ddg-video-editing-playbook
description: >-
  Use when editing any DDG (Digital Dynamics Group) video: long-form YouTube
  vlogs, Shorts/vertical clips, thumbnails, or social video graphics. Holds
  Markus's standing editing and brand rules, the MANDATORY edit workflow
  (pre-flight checks, preview-first, feedback log, scorecard) and the lessons
  learned from each edit.
---
# DDG video editing playbook
These are Markus's standing rules, added to as he gives feedback. Follow every rule on every DDG video. Cattle Dog Coffee content is separate and has its own brand.

- **HARD RULE: every product, service or company he mentions goes on screen (Markus, 23 Nov 2026, repeated after Ep2 missed the Mynbyn printer at 4:50).** For EVERY mention (scan the full transcript for product, brand, company, app and service names before building, and log each one in a mentions checklist), show it in the moment: official logo + a screenshot or product photo pop-up, or a smooth scroll of its website/product page (pop-ups closed). On brand, above the webcam, >=4.5 s. Public brands are not blurred; private businesses he is tied to follow the blur rules. Preflight FAILS if any logged mention has no on-screen visual.

- **HARD RULE: blurs never flicker (Markus, 24 Nov 2026, after the Ep2 v2 game-dev screen blur at 6:25 flickered on and off and hid nothing).** Never drive a privacy blur from per-frame OCR or detection boxes. For any text that scrolls, updates or moves (logs, consoles, chats, page flips), blur the WHOLE region it can occupy with ONE steady rounded box held for the entire span (the union of every detected position plus padding), fading only at the span edges. Detection only finds WHERE and WHEN; the box itself must be constant. Gaps under 1 s between spans get bridged. Gate G8b 'blur stability' (mandatory, master + every Short): FAIL if any blur drops for even 1 frame inside its span, or if OCR reads anything inside a blurred span (checked at 10 fps). Include a before/after frame strip of any changed span in the review.

- **'Edit' sequence (Markus, 24 Nov 2026):** when he does the crazy-movement 'edit, edit, edit' bit, EVERY spoken 'edit' gets a short decaying screen shake and the edit-callout animations fly all over the full frame, escalating each time (Night Glass, white streaks OK, no big blue circle, never covering his face beyond a flash).
- **Freya avatar (Markus, 24 Nov 2026):** the floating avatar always faces toward the main content/centre of the frame, never the screen edge, and is NEVER under a blur (composite above all blur layers). Preflight fails on either.

- **HARD RULE: never cut or mute his words for privacy (Markus, 24 Nov 2026).** His voice stays 100% unedited in content: no privacy mutes, bleeps or dropouts (they sound weird and jumpy). Privacy is handled visually only. The ONLY audio censor is swears (static noise ONLY, no TV icon on screen; Markus 24 Nov 2026), and swears means ONLY 'fuck' and 'shit' and their forms (Markus, 24 Nov 2026); never censor any other word. Still do loudness, leveling, smoothing and noise reduction. Gate G5b fails on any non-swear mute or dropout.

- **Dramatic zooms (Markus, 24 Nov 2026):** a dramatic zoom is a SLOW gradual push-in over 3-5 s (eased, starts slowly as he goes down the rabbit hole), then a quick SNAP back out when he stops. Never a quick in-and-out. Fast punch-ins are only for impact moments like the 'edit' shakes. Focal point = his WEBCAM (bottom-left): push diagonally from top-right toward bottom-left with the scale origin anchored at the bottom-left corner so left/bottom edges stay pinned and the frame stays filled; never a generic centre zoom, never centred on the webcam (shows cropped borders).

- **Webcam windows (Markus, 24 Nov 2026, replaces 20 Nov 'no need to blur the window'):** blur ALL windows in his webcam shot EXCEPT the one directly behind his head. Exact per-pane window-frame masks defined ONCE in webcam-local coords and attached to the webcam element (follows its position/scale); no per-frame dynamic tracking (usage). Person matte keeps him sharp. Swear censor = audio static only (no TV icon), 30% quieter than Ep2 v2 (gain x0.7).

## MANDATORY edit workflow (Markus approved 23 Oct 2026; never skip a step)
Goal: get it right first time and refine the process every episode.
1. **Start**: read this playbook, /workspace/ddg-video-toolkit/feedback-log.md and scorecard.md. Copy the scripts from /workspace/ddg-video-toolkit/ep1_scripts/ into the new episode folder and adapt them (audit.py, clip_audit.py, clip_open_check.py, face_check.py, sub_qa.py, overlay_track.py, make_ep.py, make_clip.py, graphics.py, coldopen.py, build_srt.py, chapters.py, finish.py, bts.py).
2. **Preview first**: before any full render, build a short low-res preview (the opener plus 1-2 clips, or the riskiest 60 s windows) and get Markus's thumbs-up through the usual chat. Overlay placement fixes then cost minutes, not a multi-hour re-render. Skip only if Markus says to.
3. **Pre-flight checklist**: run ALL automatic checks before delivering anything; Markus only ever sees a version that already passed. Fix and re-run until clean, then report the results in the delivery message:
   - Overlays: no overlap in time and space, combined <= 75% of screen (Markus: 50% -> 62.5% on 24 Oct -> 75% on 25 Oct 2026), every quick pop-up (sticker, callout, chip, short label) >= 4.5 s; every text-heavy pop-up (info card, funding note, company graph/org chart, checklist, Freya intro/tag, end screen) >= 15 s (per-type minimums in audit.py: HEAVY_KINDS).
   - Face clearance: no overlay on or near Markus's face (clear margin of about 15% of frame width around the face box).
   - Subtitles cover every spoken stretch (no gaps > 3 s with speech, no drift > 0.3 s); also the 3-minute-interval spot checks.
   - First 2 s are a fade-in from black with no dialogue; clips start at the beginning of a sentence and finish it.
   - Blurs present on every frame needed: Chrome tabs + URL bar, real revenue figures, emails/keys (OCR scan), chat to Freya (Freya's replies visible), left-side Claude/AI chat panel.
   - No reshoot / second-attempt wording anywhere (overlays, description, BTS).
   - Quality: master 8-12 Mbps, true 1080p, review copy as high as the size cap allows; audio -14 LUFS, true peak < -1.5 dB.
   - Spoken privacy mentions (e.g. 'cattle dog') flagged to Markus.
4. **Feedback log**: every note from Markus becomes a rule with a reason and an automatic check in /workspace/ddg-video-toolkit/feedback-log.md, and a line in this playbook, the same day. Also record what he liked so it gets copied.
5. **Scorecard**: after each delivery, update /workspace/ddg-video-toolkit/scorecard.md with the number of fix requests Markus made and any repeated mistakes. Target: trending to zero. A repeated mistake means the pre-flight check was missing or not run; fix the check.
6. **Don't call it complete** until every item on the request checklist is verified and ticked.

## Brand: Night Glass v5 (applies to every graphic, pop-up, caption and cover; replaced Glacier Glitch on 23 Nov 2026)
- Graphite #141518 ground and frosted glass panels (blur under the panel, rgba(16,18,24,.52) fill, thin white 8-10% border, rounded 14-16 px). Never dark blue, never a flat generic box.
- **All text is white**, in Geist (headings/body/subtitles) and Geist Mono (small kickers and labels, tracked caps). At most ONE Ice #7CC9E8 accent per element (a 1-2 px line or a dot); never text on Ice. Brand green only for ticks.
- No emojis anywhere (captions, chips, cards, titles). No robot images or emojis, no red numbers, no glitch effects on new graphics.
- Motion: back-overshoot drops and slide-ins, scale-in pop-ups with a small overshoot, draw-on lines with a leading Ice dot, quiet whoosh/tick SFX well under the voice.
- The ONLY glitch-logo elements left are the official intro/outro animations (rule below), used exactly as supplied.
- Reusable code: /workspace/deepdive-ep1/full/build/ngx.py + gfx_full.py (label_img, info_img, factcheck_img, agenda), /workspace/deepdive-ep2/v2/pv2.py (HUD, subtitles, pop(), censor TV).

## Official brand animations (supplied by Markus, 23 Oct 2026)
Use these as supplied; never recreate or restyle them. Copies are in /workspace/ddg-brand-animations/.
ALWAYS use the official intro/outro exactly as supplied (glitch logo included). Never substitute or restyle them, even if a newer brand guide (e.g. Night Glass v5) conflicts (Markus, 30 Oct 2026). Shorts end on the reel outro as in s2_09 (2x speed, first 1.5 s). There is no vertical intro, so Shorts open on the hook card.
- Long-form intro (16:9, ~15 s, "DDG Intro 15s (Share).mp4"): the standard DDG long-form intro. It goes after the cold open and before the title card. Normalise its loudness to match the voice.
- Shorts/Reels end card (9:16, ~3 s, "DDG Reel Outro 3s (1080x1920).mp4"): "FOLLOW THE JOURNEY". Plays at the end of every vertical clip.
- Stand-by sting (16:9, ~5 s, "DDG Site Loader 5s (1920x1080).webm"): general-purpose.

## Long-form episodes (around 20 min vlogs; the tracker and 30-60 s commentary rules below apply ONLY to these, not to the ~2 h deep-dives)
- Structure: (1) fade in from black (2 s) before any dialogue, (2) cold open: a short highlights teaser; for Ep 1 it was self-contained moments, each centred on 4-5 s of dialogue and always finishing the sentence, (3) the 15 s DDG intro animation, (4) title card, (5) the episode, (6) end screen with subscribe / next-episode prompt.
- Keep his talking continuous: a light edit with no cuts, except dead air and false starts at the very start, which get cut.
- Burn subtitles in at the bottom, synced to the audio. Provide a .srt too. Subtitles must cover ALL speech with no drop-outs (Ep 1 lesson: ASR left holes in the transcript so subtitles vanished at 3:20; fill holes by re-transcribing without VAD and check coverage automatically).
- Blur only sensitive info with ROUNDED-EDGE, SOFT-FALLOFF (feathered) masks, never hard rectangles: usernames, emails, keys, real revenue or bank figures, customer names, his Chrome browser tabs, his chat messages to Freya (Freya's replies stay visible), and the whole left-side AI/Claude chat panel and chat history list. DDG Finance paper-trading and dashboard cash figures may stay visible.
- Cattle Dog Coffee is NO LONGER hidden (Markus, 24 Oct 2026): never blur or bleep the CDC name. On his FIRST mention of CDC in an episode, show the CDC pop-up: phone mockup with a smooth mobile scroll of cattledogcoffee.com.au, then the Instagram profile @cattledogcoffee (signed-in UI cropped out), URL + handle labels, clean and understated, >=15 s, clear of his face.
- Over-the-top touches at funny moments: punch-in zooms, light shake, SFX (synthesized or free only), on-brand pop-ups. Fun but never obnoxious: SFX quiet, always well under the voice, no stacked or loud hits.
- Freya's voice is dry, deadpan humour, used sparingly and never at Markus's expense. Never invent facts.
- Freya commentary: small on-brand captions on what is actually visible on screen behind him, every 30-60 s where it is worth it.
- When he lists things, show a large on-screen checklist (about 40-45% of frame width) with an animated green tick as he says each item.
- Persistent four-business tracker (coffee beans, health & fitness, finance / automated trading, creative outlet), highlighting the one he is talking about, in the order he covers them.
- Company graph that builds as he speaks: Markus, then the DDG company, then the businesses, then the AI bot employees, then the AI tech stack doing 24/7 automated development.
- When he talks about the AI employees, show each on screen with their name, role and trained expertise (public-safe, no company specifics). When he introduces Freya, show her self-intro: how she was trained and her basic procedures and schedules, no company specifics.
- Honest joke captions Markus requests (e.g. the Funding Note: no money to trade with, only the coffee business earns, starting from genuine zero) stay on screen as long as he says (the Ep 1 Funding Note was 20 s).
- "Edited by Freya" tag and intro callout: large, about 1.75x the original size. Be open that Freya is the AI editor and that DDG is building in public. NEVER mention that an episode is a reshoot or a second attempt.
- Retention practice: hook in the first 30 s, pattern interrupts every 30-60 s, mid-video re-hooks, chapters list for the description, end-screen CTA. See /workspace/vlog/longform-best-practices.md.
- Audio: light noise reduction, gentle compression, -14 LUFS, true peak below -1.5 dB.
- Zooms and shakes must be smooth. After any timeline shift, re-check every effect's timing.

## Overlay rules (Markus, 23 Oct 2026, from the Ep 1 audit)
- Overlays must NEVER overlap each other in time and space.
- Overlays must NEVER cover Markus's face and must stay well clear of it (not next to or near it): keep a clear margin of about 15% of frame width. This applies to clips, the BTS clip and episodes.
- All simultaneous overlays combined must take up no more than 75% of the screen (Markus, 25 Oct 2026; was 62.5%, originally 50%) (include the persistent tracker; exclude subtitles and the small watermark). If an overlay breaks either rule, delay it to a clear section, shrink it, or skip it.
- Per-type minimums (Markus, Ep1 v10; LONG FORM ONLY since 23 Nov 2026, Shorts use quicker beats): quick-edit pop-ups (stickers, callouts, short labels, chips) at least 4.5 s; pop-ups with lots of text/context (info cards, funding note, company graph, checklists, intro/tag cards) at least 15 s. Merge many short cards into ONE card that builds line by line rather than stacking 8 x 15 s cards. If it cannot get that long without breaking the rules above, move or drop it.
- Build an automated overlay timeline check (bounding boxes per frame, including the face box) and run it before every render; the start of the video is the usual trouble spot.

## Clips (Shorts/Reels/X)
- Make at least 5 clips of about 20-30 s from the best moments, each independently watchable (Ep 1: 10 clips at Markus's request, since the episode had many good moments). Cutting sequences together is fine. Markus names moments he wants as clips; always include them.
- Format: vertical 1080x1920 on a SOLID BLACK background (no blue or blurred fill), with the glitch icon top-left.
- Open with a hook in the first 1-2 s plus an on-screen hook title. Captions are word-by-word in brand style, kept out of the bottom ~20% and the right edge. Start at the beginning of a sentence and finish it. Stickers/cards sit well away from his face.
- Trim dead air, bleep swears, master to -14 LUFS. End with the 9:16 "FOLLOW THE JOURNEY" outro.
- Also make a ~30 s vertical behind-the-scenes clip of how Freya edits, using real steps, no company specifics.
- Markus liked the Ep 1 v9 clip style (clips 7 and 8), apart from overlay placement near his face.

## Quality and delivery
- The source is 1280x720@60. Upscale to 1920x1080 with a good scaler and high bitrate (master roughly 8-12 Mbps). Heavily compressed review copies look blocky: Markus noticed the episode looked pixelated in VLC and Windows Media Player while the clips looked fine. Never judge quality on the small Drive copy; deliver the highest-quality copy that fits, and keep the master on the box.
- Send Markus playable MP4s (VLC-friendly) under 200 MB in chat. The Drive tool caps at about 100 MB, so chunk or split bigger files.
- Check the first seconds: dialogue must not be cut off at the start.
- QA frames at every new element, at 3-minute intervals, and across every overlay window before delivering.

## Process and lessons learned
- Update existing files in place. Don't create duplicates; trash superseded Drive copies. Reuse project files, transcript and audio; batch feedback into one render.
- Don't use raw footage in content until Markus says it is final (he sometimes reshoots).
- Drive folders: DDG Company Vlogs > 1 - Raw Uploads / 2 - Edited Episodes / 3 - Clips.
- Big raw files (700+ MB) must be chunked from Markus's PC; it takes about an hour, so ask for the upload early.
- Render long episodes in 60 s windows, one ffmpeg at a time (long single renders ran out of memory). Memory lessons: merge blur masks into one branch, use single-frame mask inputs rather than -loop 1 streams. Keep a PROGRESS.md and make every step resumable.
- Ask Markus for specifics early (intro, outro, names) and flag spoken privacy issues before delivery, not after.
- Give Markus a % update when he asks and at 75% if requested; don't call a job complete until every item on the request checklist is verified.
- Never upload or publish to YouTube or X until Markus says so.

## Source resolution rule (added 23 Oct 2026)
- Ep1 raw was recorded at 1280x720, so the 1080p export is an upscale and cannot add real detail (looked soft/pixelated in VLC/WMP).
- From Episode 2 onward: Markus records the raw at 1080p or higher (screen recording and camera). Pre-flight must check the raw's resolution first and flag anything below 1080p to Markus before editing.
- Deliver a 1080p, high-bitrate master; chat copies are capped at 200 MB, so also give a Drive link to the full-quality file.


## Lessons from Ep1 v10
- Keep the opener design Markus already approved (Ep1: 3 short moments + hook card); do not redesign it unprompted. Cut every moment on gate-silence boundaries and whisper-check the final audio.
- ffmpeg 7.1: `tpad=start_mode=clone` silently adds nothing after fps+setpts; hold the first frame with `loop=loop=60:size=1:start=0,setpts=N/30/TB` and verify frame count and A/V length (a missing freeze desynced the v9 opener audio by 2 s).
- Apply the clips' webcam look (eq contrast 1.04/saturation 1.08 + unsharp 5:5:0.6, lanczos upscale) to the facecam patch in the episode too.

## Recording settings that passed (24 Oct 2026, Markus's PC: RTX 3070 Ti, Streamlabs, Logitech USB 1080p webcam)
- Streamlabs Video: Base 1920x1080, Output (Scaled) 1920x1080 (was 1280x720 default, the cause of the Ep1 low quality), 60 FPS.
- Output > Recording: Advanced, MKV then remux to MP4, NVENC encoder, CBR 25000 kbps, keyframe 2, record to F: or D: (C: hits 100% disk).
- Test clip verified: 1920x1080, 60 fps, HEVC, ~25 Mbps, crisp screen. Webcam is a small, slightly soft box; raw behind-the-scenes look is acceptable to Markus.
- Pre-flight: check raw resolution/bitrate with ffprobe before any edit.

## Lessons from Ep1 (24 Oct 2026, reshoot footage, 1080p60)
- Markus's structure for split recordings: fade (1 s) -> opener (3 moments, natural length, finished sentences) -> 15 s intro -> Part 1 to the exact cut -> 2-3 s DDG "technical difficulties" hold (static/glitch, light joke) -> Part 2 -> end screen. Keep ALL effects subtle (gentle easing, soft shadows, simple fades/slides, quiet SFX).
- afftdn adds a fixed 25 ms (1200 samples @48k) audio delay: after any denoise, cross-correlate processed vs source audio and shift it back. Run the objective sync check (audio cross-correlation + webcam-crop frame match) on every opener moment and window.
- Whisper can stretch one word over a 3-15 s span and hide dropped speech; gap checks miss it. Re-transcribe every word longer than 1.5 s (fill_long.py) and check speech-energy-without-words (holes.py). Opener subtitles are built only from the words inside each moment.
- Burn subtitles right of the webcam (MarginL 780) so they never sit on his face; overlays live at x>=960 (or y<=360) for the standard Streamlabs layout.
- Blur detection: layout-specific static boxes (Grok sidebar preview lines, Claude left panel + reply box) + colour-detected chat bubbles (Markus's) + full-res OCR for emails/keys/IDs and words like "reshoot". Re-OCR the finished preview to prove nothing sensitive is readable.
- Ep1 final (24 Oct 2026): pick opener moments for energy and curiosity (bold claim, money, a punchline), not just clarity. Blur detectors must handle every UI row state (selected sidebar row = bg 31, not 13). When a browser shows private dashboards (revenue, signed-in email), blur the whole browser window for that span. Render windows with ABR 11M (maxrate 26M) to hold the ~9 Mbps master floor. Exclude persistent overlays (tracker) from blur-detail metric regions.

## Lessons from Ep1 master v2 (24 Oct 2026, Markus's graphics audit)
- Card text must auto-fit: titles shrink to the card's inner width (gfx2.fit_title, min 30 px, then wrap); never let a title run past the panel ('HARD LESSONS' title was clipped at the card edge). Card height is derived from the content/layout, never hard-coded (company graph's 'AI tech stack' node sat outside the frame).
- Inner boxes (graph nodes, number badges, counters) use gfx2.frost_tile: white sheen gradient, top highlight, inner bottom shade, tinted border. Flat 5% white fills do not read as frosted glass.
- Backdrop blur covers each overlay's FULL footprint plus a 26 px halo (render.py blur_box), not just the opaque panel: the AI chat's feedback icons (copy/like/retry) showed under the company graph.
- Mandatory gate before every render: `python3 gfx_audit.py <plan.json>` (A1 bounds/clipping/padding, A2 frosted panel + tiles, A3 no overlapping panels incl. the tracker), and after every window render `python3 gfx_audit.py <plan.json> <window.mp4>` (B: halo band must be blurred and OCR-clean). Any FAIL blocks delivery.
- v2 editing density (Markus): ~60% of runtime carries an edit, >=40% stays clean (persistent tracker excluded). Add '// QUICK CONTEXT' explainer tooltips for terms (>=4.5 s) and occasional intro-style motion graphics (mg.py: HUD ring + glitch icon + title wipe + digit counter). Items shown while the business tracker is up go at y>=90 so panels clear it.
- ImageDraw on RGBA replaces alpha: draw fading/translucent text on a separate layer and alpha_composite it, or you punch holes in the glass.
- Fact-check (Markus, Ep1 v2): fact-check every factual claim with web sources; flag only clearly wrong and verifiable ones (skip opinions, jokes, hedged rough estimates). Each gets a 15 s frosted 'FACT CHECK #n' card (SAID vs ACTUAL + short source + footer 'Markus gave Freya permission to correct him after the fact') and a small 'MARKUS WRONG [n]' tally badge above it (digit rolls up, one soft tick). Table in FACTCHECK.md (claim, timestamp, verdict, correct info, source URL). gfx2.factcheck, mg.wrong_counter.
- Render windows must still hit the ~9 Mbps floor: CRF16 on static screen footage gave only 3.7 Mbps; use ABR 11M (or re-encode the concat at 11M).

## Freya co-host format (Markus, 24 Oct 2026, Ep1 master v2 final)
- Editing density: overlays may cover up to 75% of the frame at once (gfx_audit.py AREA_CAP=0.75); target ~60-65% of runtime edited, more animation/intro-style graphics welcome. Still never on/near his face, never overlapping.
- Freya co-hosts every episode: white Freya avatar (freya_avatar_white.png, freya.py avatar_mov) fixed bottom-right (disc centre ~1820,940), idle breathing/glow, bounces while a bubble is up; present for the whole body (P1/P2 windows). Bottom-right clears all webcam layouts (A/B/C bottom-left); if a layout ever puts the cam bottom-right, move her to the nearest safe corner.
- Most captions/stickers/tooltips/short fact-checks become frosted speech bubbles from the avatar (freya.bubble_mov, kicker '// FREYA', emoji, soft pop at -24 dB-ish). One bubble at a time, >=0.25 s apart, 6-9 s each (fact-check bubbles 15 s with source + 'MARKUS WRONG: n' tally). Long info cards/graphs/checklists stay cards. Speech subtitles stay normal; set render.SUB_MR=330 with pixel-aware 2-3 line wrap (right edge <=1590) so subs clear the avatar, name row and bubbles.
- Bubble voice: playful, short (<= ~70 chars), first person as Freya, accurate; never invent facts.
- Shorts: approved Short 7 style (no avatar) unless Markus asks for it.
- Avatar style (approved demo, 24 Oct 2026): freya_av.py (from /workspace/freya_demo_work/render.py). freya_avatar_white.png already faces LEFT - never flip it again. Floating 'Freya' name with gentle bob + status pill (general: thinking..., agreeing, concerned, listening, impressed; fun: taking notes, fact-checking, side-eye, proud, mind blown, loading brain..., vibing) matched to the transcript every ~20-60 s, crossfaded, subtle eye bias. Hide the name/pill row under team/graph cards; fade the whole avatar under big mockups.
- Wild vs calm: at most ~25% of animation events may be wild (fly-arounds, spins, mind-blown pops, vibing sway capped 8 s); 75% calm. Report the ratio every delivery. Fly-around = 2.6 s arc + 360 spin rotated about the CENTRE (bottom pivot clips the blob), always above the subtitle band.
- Bubbles: never over subtitles, never during a face punch-in (final_check flags it), never over crisp busy UI (gfx_audit stage B 'crisp detail'/'text visible' fails) - drop or move that bubble.
- Shorts: small avatar (scale 0.5) under the captions, centred, eyes up toward his webcam (EYE_BIAS -3,-20), never over face/captions/hook; stickers moved to y 1610; witty bubbles only where they add rewatch value (some clips avatar-only). Fact-check bubbles for wrong claims (e.g. 'Claude's API isn't free'). preflight_short.py retries whisper when it returns no words; ends_sentence may false-negative when the source transcript lacks the last word - verify by ASR and triage manually.


## Markus v3 notes (25 Oct 2026, after watching Ep1 v2)
- Freya appears in the cold-open moments too. Fly-across (fly_across.py): squish to a small white ball + motion streak, <=1 s (0.8), present the pop-up beside it, fly back when it ends; at most once per minute; path never over face/webcam or subtitles.
- Jokes: light societal-stereotype roasts are fine; never religion, race or other protected groups. Fun facts need a verified source URL. 4th-wall shocked look (eyes swing to camera, wide, jolt, pink '!') at a couple of moments.
- More scrolling B-roll (sites, articles, products) and real news-article screenshots with source credit; keep something engaging on screen most of the time, within the 75% cap.
- Employee list = title + specialised role, no group chats. Plan B = job applications Jan 2028 if 2027 Plan A fails.
- Blur continuity: every blur region must be present on every frame (automated per-frame check); backing blur behind pop-ups feathers toward the edges.

## v3 standing rules (Markus, 25 Oct 2026)
- Overlay cap 75% combined; never over webcam/face or subtitles.
- NO "YouTube slop": no SFX spam/meme sounds (subtle low whooshes at most); zooms rare and slow; animations only where they add meaning; aim >=3-5 s clean frame between cards; fly-across <=1/min; 4th-wall shock max 2 per episode. Classy, not frantic.
- Stats cards for things he mentions (companies, platforms, AI tools, markets): verified numbers only, source + year on screen.
- Partner's flower business = @bloom.bar.co (The Bloom Bar) phone mockup, crop Following/Message + "Followed by".
- Deliver 2-3 thumbnails (1280x720, Markus looking good: smiling/expressive, eyes open, sharp) with each master.
- Blur continuity: every frame must keep sensitive regions blurred; run blur_check.py (per-frame, independent detection) and fail on any gap.

- Business sections: persistent frosted "key points" panel above the webcam, bullets (3-6 words, his words) added as he says them, clears at next topic; counts toward the 75% cap; other pop-ups must not collide.

- v3 additions (25 Oct 2026): persistent Social Footprint + money line (real dated data, config file; "Spent (business ops)" excludes subscriptions); real-logo business tab bar; finance sections carry a persistent paper-trading disclaimer line; index/hedge-fund mentions get sourced charts/benchmarks; jargon gets on-screen formula cards; economy mentions get non-political sourced headline screenshots; brand mentions get the framed brand PDF scroll + muted intro animation; congress-trading = reported figures only with source/year, no accusation; illustrative photos are labelled as such. Webcam background blur: do NOT do (Markus skipped it).
- Verify market claims against index closes for the recording date before fact-checking; polite check, not a WRONG unless clearly wrong.

## 2026-10-25 v3 final rules (Markus, 07:51-07:56)
- Stats HUD (top-left) = v1 two-group tile strip (SOCIAL FOOTPRINT | BUSINESS · AUD · SINCE START, tiny-caps labels over bold values, icons, net red/green, one small "as of" note, "goal: grow" tag). NO extra rows; the finance paper-trading disclaimer is a SEPARATE small frosted note (finance section only), never attached to the bar.
- Business tab bar (top-right) matches the HUD exactly: same top/bottom edges, panel height, corner radius, border, frosted style; verify pixel-by-pixel (edges within 1 px) on a 1080p still before rendering. Persistent overlays are always on screen, so they must be flawless.
- Automated TEXT-FIT check before every build: every text element inside its card with padding, no overlapping lines, no overflow/clipping, measured programmatically (text boxes vs card bounds and vs each other) for every card in the plan; any violation FAILS the build.
- Company/brand mentions: show that company's OFFICIAL logo on its card (header or credit chip) for credit/attribution (official site, press kit or Wikimedia; editorial use only). Our DDG mark only on DDG cards.
- News screenshots: never settle for the first article; compare several reputable sources and pick a visually strong one (hero image, clean headline layout, readable), accurate and credited. Applies to every news card.
- Freya self-intro bubble right after Markus introduces himself (~30 s into his part): Freya, DDG's AI Marketing Director + co-host, does ALL the video editing; 5-8 s; not over face/subs.
- When Markus discusses Freya's video editing: play the WHOLE behind-the-scenes editing clip, muted, framed pop-up (<=75% combined overlay), never over webcam/subs; his audio continues.
- JOB TIME LOG: log real AEST start/end/duration + my estimate for every edit job in /workspace/ddg-video-toolkit/job_time_log.md; use it (not gut feel) to estimate future jobs.
- Final preflight before delivery: per-frame blur continuity, text fit, subtitle coverage, overlay overlap + 75% cap + never face/subs, 1080p60 bitrate/pixelation, audio levels, OCR for sensitive text, SHA256 verified on the PC. Write PREFLIGHT_FINAL_vN.md.
- HUD (stats bar) = icons/logos + values ONLY. No caps labels (no "SOCIAL FOOTPRINT", "goal: grow", "YOUTUBE · date", "SPENT (BUSINESS OPS)", "NET" etc.) and no "as of" date. "Users can infer what those numbers and logos mean, it's a progress tracker." Panel height must stay identical to the tab bar (same top/bottom edge, <=1 px).
- NEVER red for numbers or negatives anywhere (HUD net, cards, charts). Use warm orange #FF9F43 (255,159,67). "Red numbers scream bad." Trademark logos keep their own colours (e.g. the YouTube red play button).
- SNAP GRID for every overlay: layout_grid.py (1920x1080, 12 columns, 20 px safe margin, 16 px gutter, 8 px baseline, content row 1 at y=112 under the bars). snap_grid.py snaps every panel's anchored edge (left panels to a column start, right panels to a column end, with 1900 flush with the tab bar) and its top to the baseline. Stacked or adjacent co-visible panels share edges exactly. Speech bubbles and tags that follow Freya are exempt.
- Build gate: align_check.py (edges of every panel on grid lines <=1 px; bars exactly at x0=20 / x1=1900, y 20..92; stacked co-visible panels' edges equal; 16 px gutter under the bars) runs with text_fit_check.py and gfx_audit.py. Any failure = fix before rendering.

## 2026-10-25 v3.1 final rules (Markus, 11:20; HUD approved 11:26)
- **Stats HUD = a left-to-right equation, expenses first, profit last:** `[spent] − [debt] = [gross earned]  |  ♥ [charity]`. That is $2,711.40 − $1,754.50 = $956.90 | $33. Spent AND debt are orange #FF9F43, earned is green, charity is pink. Use small faded −/= glyphs, icons + values only, no labels, never red. The equation must balance (hud_v31.py asserts it). Show Markus a still before changing the HUD.
- **Blanket background blur on every screen-share frame:** the whole Claude panel and the whole Grok Bot chat are blurred (384x216 downscale + gblur 2.0). White text should still show as moving smears, but no word can be read. The AI-employee list on the left (x<338) stays sharp, but its preview lines keep the strong sensitive blur. The taskbar stays sharp. The trading platform / finance dashboard (Chrome full screen, and the dashboard half in layout B after the CDC admin) is NOT blurred, because it is paper data. All the sensitive-region blurs still apply on top.
- **Blur never bleeds into the webcam:** every mask (sensitive, blanket and overlay backing) is cut out of the detected webcam rect with a hard, clean edge (blurmask.camrect: p1 (0,658,750) then (0,679,712); p2 (0,679,712) then (0,778,537)). blur_check_v31 checks webcam fidelity (PSNR >= 30 dB vs source) and blanket unreadability 2x per second.
- **Key-point panels hide while a dashboard/trading platform is on screen.** Show them before or after the dashboard view. The small paper-trading disclaimer note can stay.
- **Cut-outs must be clean or framed:** a product cut-out needs a proper matte (no ragged edges, no dark halo). Otherwise, show the original photo in a clean rounded framed card with its own background, which looks intentional. If neither looks good, drop it.
- **Intro reels must be complete sentences:** never start or end mid-sentence. A short punchline moment (e.g. "Alright, we're back") can close the reels. The "1 human. 9 AI employees." hook card comes AFTER the 15 s DDG intro animation.
- **Fact-check every number against the stats HUD:** bag counts, charity totals and revenue on cards and bubbles must match the HUD config. If Markus says a wrong number on camera, the subtitles stay verbatim, a polite Freya bubble corrects it ("Actually: …"), and the description's "Markus wrong N times" count goes up.
- **Gag graphics** (e.g. the dumpster fire for "the economy is on fire") are stylised flat-vector motion cards in the brand glass frame, 3–6 s, with Freya flying over to point and label them. Keep them light and non-political.
- **Rendering:** render part 2 at NP=1 (p2 windows peak at 3–7 GB each and caused 3 OOMs at NP>=2); part 1 at NP=2.

## 2026-10-25 v3.2 final rules (Markus, 17:17–17:36)
- **Freya morph animations (approved style, keep MINIMALIST):** the avatar squashes and stretches, then streams as white strands into white line art in one grid panel (SMALL 1126,112–1900,592 or BIG 968,112–1900,744). Use few decorations, clean 2–2.4 px white lines, a single cyan glow only on the leading dots, smooth easing, and NO motion blur. The panel border draws itself, then the title appears (Space Grotesk 30). No kicker, no line halo. Small source line at the bottom. It retracts back into the avatar. Real data only, with every number traceable to a source. Use ~8–12 per long-form episode wherever a graphic explains what he is saying. Engine: /workspace/v32/morph.py + scenes.py (`python3 morph.py <S> base|stills|render`). Review contact sheets before rendering.
- **The HUD runs as an equation through to net profit, with short labels UNDER each number** (this supersedes "values only" for the money tiles): expenses (orange) − gross revenue (green) = debt (YELLOW 255,214,92) | charity deducted (pink) → net profit (orange, never red). The script asserts that the numbers balance. Render a still first.
- **AI existential-dread jokes (Freya):** light, self-aware jokes about being an AI employee (usage limits, context windows, chats ending, render queues, unpaid internship). Keep them SHORT, never dark, rude or bleak, and never making DDG or Markus look incompetent. Use Markus-approved lines VERBATIM. Each stays on screen ≥4–5 s (7 s bubble standard). Space them across the episode (one every ~3–5 min). Report the timestamps. About 20% more jokes/fun facts than v3.1. Every fun fact needs a verified source URL.
- **Veteran mention:** use only public-domain / properly licensed photos (US DoD/USAF/RAAF via Wikimedia Commons). Credit the photographer + "public domain" on the card, label them "representative photos", and keep the tone humble (no bragging).
- **Website scrolls:** close every pop-up (cookie banners, Christmas promos) before capturing, so the page is never darkened (playwright: click the dismiss button, then a full-page screenshot).
- **Late edits without the original assets:** if the gfx work dirs are gone, do NOT re-render the full episode. Render replacement segments from raw on the box (render.render + regenerated bubbles + avatar), copy them to the PC, and composite them onto the previous master ON THE PC with ffmpeg + NVENC (HUD swap = blurred patch + new HUD per footprint span with matching 0.4 s fades). Pulling a master back to the box is infeasible (CopyToBox ~11 min per 60 MB; F: is refused). Give every secondary stream its own input (`-ss/-t`), never a split+trim of the main stream (framesync buffering → OOM).
- **Calibrated estimates (Markus, 25 Oct 18:22):** before quoting any time estimate, run `python3 /workspace/ddg-video-toolkit/estimate.py predict <gut_minutes>` and quote the calibrated figure plus its range. After every job, run `python3 estimate.py log "<job>" <gut_min> <actual_min>` (history: estimate_history.json). Also log the job in job_time_log.md.
- **PC ffmpeg 9 gotchas (v3.2):** use `-/filter_complex file` (not -filter_complex_script); convert to rgba before cropping odd widths; timeline `enable` must use `t` (between(n,...) never fired). CopyFromBox: push files in ≤8 MB chunks (two calls at a time), reassemble on the PC and verify SHA256. Test-encode the first ~240 s and check frames before the full NVENC run (~3.5x realtime on the RTX 3070 Ti).

## Deep-dive motion rules (Markus, 11 Nov 2026, after deep-dive sample v1)
- **More dynamic and fun, still Night Glass:** use back-overshoot drops and slide-ins, draw-on line art with a leading Ice dot, and pop-up windows that scale in with a small overshoot. Freya squashes, stretches or hops on cue words. A short line-motion burst or ink splash plus a small shake (5 px, 0.3 s) goes on the big beats. Keep wild events at most 25% of the total.
- **Every graphic (morph, pop-up window, panel, bubble, chip) stays on screen at least 10 s** (text-heavy cards still at least 15 s). Bursts, ink and shake are entrances only. Check it with qa_v2.py graphics_min_10s.
- **Pop-ups must be READABLE and grid-snapped (RULE, Markus 12 Nov 2026 08:16):** any pop-up meant for the viewer to read (checklists, lists, cards, pages) must be large enough to read comfortably on a phone, so use screen space generously; viewers aren't watching the dashboard or finance page behind him. Always place pop-ups on the grid-lock snap positions (big grid panel by default). Still keep them clear of his face and the subtitles.
- **Pop-up duration = topic duration (RULE, Markus 12 Nov 2026 08:16):** a pop-up for a topic stays on screen for the WHOLE span he talks about that topic, from the first mention until he moves on, not a fixed 10 s. For list pop-ups, highlight the current item as he works through it. Audit every pop-up against the transcript spans before delivery.
- **Pop-up scrolling pages wherever they fit:** a glass browser or editor window showing a real captured page or screen scrolling. Examples are the YouTube Shorts grid, the CDC site, and "Freya's edit desk" (the real plan file scrolling, with a line-art timeline). Capture headless with popups dismissed and blur or remove anything private (for example, drop location lines from code shown on screen). Engine: deepdive-ep1/v2/build/fx2.py.
- **When Markus cues Freya on camera** ("Freya, edit", "do shaky things", "do cool animation now"), hit each cue word with its own distinct animation.
- **Never let a number or % count up through wrong values** on screen (v1 showed "1%" mid-count). Show the final value and animate the bar.
- **Standing blur rule (Markus, 11 Nov 2026):** ALWAYS blur anything that could identify him (surname, address, email, phone, profile photos), the people close to him, or locations near him (city/suburb/postcode, clock-city labels, window views, local clubs). Also blur sensitive company info such as the DDG Control URL, *.replit.app URLs and admin pages. This applies in pop-up pages and code shown on screen too. Gate: OCR every 3 s of the render, and the build fails on any hit.
- **Approved cuts for deep-dive Ep1 (11 Nov 2026):** 18:45, 46:30 and 47:00 (reshoot lines), 37:14-37:30 (glitch). The Jensen Huang claim (63:55-64:25) is KEPT (Markus 6:04am) with a Night Glass 'Alleged, not proven' label for the whole claim, at least 10 s.
- **Samples open like episodes (11 Nov 2026):** 'coming up' teaser cold open (quick cuts from the same episode, mixing fun/silly moments with useful info, finished sentences), then the official 15 s intro as supplied, then the section.

- Blur strength (11 Nov 2026): light soft blur on small text stays readable to OCR. Privacy blur boxes need the full box + 6 px, downscale /12, sigma ≥ 9, and must pass an OCR check of the FINAL assembled file (teaser included).

## Shorts/Reels pacing (Markus, 26 Oct 2026: "they're for ADHD people")
- 15–25 s total (hard max 30 s); reel outro trimmed to ~1.5 s.
- Hook inside the first 1 s: cold-open on the strongest line + big bold hook text at 0.00 s.
- Cut dead air ≥0.13 s, ums and stumbles; a reframe/jump cut every 2–3 s; punch-in zoom on 2–3 key words.
- Word-by-word pop captions with emphasis words highlighted (cyan).
- Freya: several short (4.4–5 s) morphs illustrating points + one edgy quip per short; something new on screen every ≤4 s.
- Subtle whoosh/pop SFX and a ducked royalty-free music bed.
- Builder: /workspace/s2/make_fast.py + plan3.py; QC: preflight_fast.py.
- Zooms softer (Markus, 30 Oct 2026): keep reframes and punch-ins but ~30% smaller and less abrupt. Levels 1.00/1.091/1.035/1.119, punch-in +0.084 with 0.17 s in / 0.25 s out, mid-shot reframes eased over 0.15 s (builder: /workspace/dd01/shorts_v2/build/make_v2.py, ZR=0.70).

## Privacy first (Markus, 29 Oct 2026, applies to every vlog, Short and edit)
- Uphold Markus's privacy as much as possible while building in public. Flag anything that could reveal his location or identity details before delivery.
- Window treatment (FINAL, Markus 29 Oct 2026 11:52): just BLUR the windows behind him (a strong blur so no outdoor detail is readable). This replaces the office-and-bots replacement idea (samples v1 to v3 in /workspace/experiments/ are archived, not used). Use the precise per-window masks from /workspace/experiments/wp3/, which track camera drift, so the blur stays inside the glass and the white frames stay sharp. Also blur the mirror on the right wall when it shows an outdoor reflection. Person matte keeps him sharp in front. Check before delivery that no outdoor detail is readable.
- **Window blur = exact frame fit (RULE, Markus 12 Nov 2026 08:11):** the webcam-background window blur must match each window frame EXACTLY: a clean hard-edged cut covering only the glass panes, with no spill onto frames or walls, no gaps, and no feathered overspill. Use a precise per-pane polygon mask, tracked for camera or crop drift, on every frame of every video (teaser included). Include a before/after webcam still in every preview and preflight report, and fail QA if the mask drifts off the frame.
- **Static blur over transitions (RULE, Markus 12 Nov 2026 08:59):** when pages flip, scroll or transition and sensitive content can move, use one STATIC square blur box covering every position the content occupies, held for the whole span. Never use per-frame tracking that can drop on transition frames. Verify at 10 fps that nothing reads.

## Shorts/TikTok animation intensity (Markus, 29 Oct 2026)
- Make Freya's line-art more intense and fun in Shorts, Reels and TikToks: it reacts to and comments on what he says. Impact beats: line art hits a screen edge or lands a beat, then splashes into a few minimalist white ink blots with a SMALL, brief screen shake (a few px, about 0.2–0.3 s). Never cover his face; captions stay readable.
- Experiment log: /workspace/experiments/ (29 Oct 2026, first test: wholesome Short restructured so the hook opens on the wholesome list, plus a retitle). Record the results here when they're in.

## Shorts experiments (29 Oct 2026)
- Experiment 001 (Wholesome recut): hook-first restructure (strongest list line first, white flash, then the full clip) + explosive honest title. Record and results: /workspace/experiments/2026-10-29_wholesome_recut.md. Builder: /workspace/experiments/wr (fx.py line-art impact layer, render.sh).
- LESSON CANDIDATE (pending Markus's approval of the preview): 'impact + mini shake': line-art icons land on key words, splash into minimal white ink blots, small shake (3 px / 0.24 s; 5 px / 0.30 s on the big beat), never on his face or captions.

## Privacy: window replacement (SUPERSEDED 29 Oct 2026 by window blur, see Privacy first)
- Archived approach: dark office with Grok Bot avatars, engine in /workspace/experiments/wp/, wp2/ and wp3/. Do not use unless Markus asks.

## Cutouts: professional standard (Markus, 29 Oct 2026)
Every cutout (person, product, logo) must look professionally done, at the level of the approved profile photo (`/workspace/ddg-profile-photo/work/README_v3.md`, scripts `refine.py` and `build_v3.py`):
- Start from a BiRefNet-portrait matte, then snap it to the real edges with a guided filter.
- On hard edges (headset, cap, props), smooth the contour and redraw it anti-aliased with a feather of about 1px. Keep soft edges (hair, fleece) natural.
- Decontaminate edge colour (sample from inside the subject) so there's no halo, and sharpen before compositing, never across the edge.
- Deblock or upscale only in a narrow edge strip. Never use AI face restoration, and keep his face real.
- Check at 100% and 3x zoom and make a before/after edge comparison before showing Markus.

## Blur scope + cue moments (Markus, 11 Nov 2026, 07:08 and 08:17; replaces older blur lines for trading data)
- **Fine to show:** his face, first name, that he lives in Australia, RSPCA, his Bunnings cap (public merch), trading/platform/dashboard figures (public on purpose).
- **ALWAYS blur:** suburb/city or any local place detail; names of family, parents, partners, friends; names of any other business he's associated with (except RSPCA); private URLs (DDG Control, *.replit.app, admin pages); anything else that could trace back to him. OCR gate on the final file.
- **On-camera Freya cue moments ("Freya, edit", "do shaky things", "do cool animation now"): 400% crazier.** Real shake 20-25 px for 0.6-0.8 s with several hits, big bursts, many strands and ink, Freya bouncing and spinning, flashes. Exempt from the 25% wild cap. Never on his face for more than a beat, subtitles readable, audio within limits.
- **Deep-dive topic tracker = AGENDA list (Markus, 11 Nov 2026 09:54):** persistent top-left dot-point agenda (intro topics + topic_outline main sections). Done = dimmed + tick, current = white bold + Ice dot/line, upcoming = faded. [SUPERSEDED 12 Nov: no scrolling window or side-quest chip inside the list.] Counts toward the 75% cap, clear of face and HUD. Show a still in the report.
- **Agenda tracker = stable compact scrolling list (RULE, Markus 12 Nov 2026 08:28, revised 08:44):** use one fixed master agenda order for the whole episode and never reorder it or insert side-quest lines. Show a compact window of about 5–7 items that scrolls smoothly along that fixed order to keep the current item in view (and scrolls back if he jumps back), so it doesn't cover too much of the screen. Only the state styling changes (current highlighted, done ticked and dimmed, upcoming faded). Side quests go only in the side-quest badge.
- **Side-quest badge (RULE, Markus 12 Nov 2026 08:29):** keep it. It's a separate, bigger, colourful and playful badge (pop-in with overshoot and a small wiggle, warm glow; this badge is the only exception to the one-accent rule) placed just below the fixed agenda list. It names the tangent and shows 'back to: <item>' when he returns. It must never shift or change the list. No 'this tab is being talked about now' indicators.
- **Agenda list moves off important data (RULE, Markus 12 Nov 2026 08:36):** the agenda list (with its side-quest badge) must never cover data he's talking about or pointing at, such as dashboard figures, Social Footprint numbers or finance data. For those spans, relocate it to the clearest corner, then return it afterwards. Every move is a fun animated glide (overshoot, slight tilt/squash, line-motion trail, ~0.6–0.8 s). Its contents and order never change.
- **Freya must be ACTIVE, never muted (RULE, Markus 12 Nov 2026 08:32):** throughout every episode Freya animates often (hops, squash/stretch, spins and reactions on cue words), drops short witty speech-bubble comments, and puts up resource/reference cards with verified sources for the tools, sites and concepts he mentions. Something from her should land about every 1–2 minutes. When he mentions DDG assets (e.g. the Discord lesson PDFs), show a scrolling pop-up of the real thing.
- **Swear censor = soft static + TV-static mouth (RULE, Markus; settled in DD01 Shorts, restated 12 Nov 2026 09:01):** censor EVERY swear in every DDG video (long-form, teaser and Shorts). Audio: the word is muted and replaced with soft static (dd01/lib/bleep.py: noise bandpass 200–1800 Hz, gain 0.0856, 30 ms fades). Sine bleep tones were rejected because they sounded stupid. Visual: the cute line-art CRT TV with animated B/W static over his mouth (dd01/tv/tvgfx_v1.py, mouth-anchored, tracked) for each censor window. Subtitles mask the word (f***). This is a preflight gate: fail if any swear is audible.

## Cross-episode consistency (Markus, 19 Nov 2026)
- Every deep-dive episode must match the uploaded Ep1 overlay, pop-up, tracker and graphic style exactly. Before editing a new episode, pull reference frames from the uploaded Ep1 and diff the new edit against them in preflight; any drift in style, position, size or animation family fails.
- Layer on top: an edgier, fun animation mix; running on-screen commentary while he's talking about each thing (not after); an article or news reference pop-up (real source, cited) whenever he mentions something that can be pulled up.
- Dog moments: when the dog comes up, cut in raw Drive footage of her running in the park and having fun, or the existing reel file of her. Never post to Instagram.
- All windows and cutaways must be cut and cleaned neatly (no ragged edges, stray UI, or half-loaded pages).

## Reel-ready framing (Markus, 20 Nov 2026)
- Not for every graphic. For any long-form moment that could become a Short or reel, place the supporting context and commentary graphic directly ABOVE his webcam, stacked so a 9:16 vertical crop (the "profile cut") captures the webcam with the context on top. Build the vertical clips from that stacked framing.

## Current front ends (Markus, 20 Nov 2026)
- If a DDG platform's front end (finance dashboard, Control page, etc.) has changed a lot since filming and Markus sends a link, show the CURRENT version when he talks about it. Use a fresh scroll recording shown big on screen: desktop frame for web dashboards (about 10s, smooth scroll), phone mock-up with a scroll for mobile pages (the Instagram and coffee page treatment he loves). Blur rules still apply.

## HARD GATE: ALWAYS check numbers and facts — every time, everywhere (Markus, 21 Nov 2026)
This applies to EVERY output, not just renders: previews, stills, Shorts, captions, titles, descriptions, posts, daily lists, chat replies. Check the live source every single time before showing a number; never assume a previous check still holds.
Freya is the source of truth for DDG numbers. A wrong figure on screen is a blocking failure, same level as an unblurred private detail or an audible swear.
- Before ANY render, preview, screenshot or still is shown to Markus, every number and factual claim on screen is checked against its source in that same session:
  - Top HUD bar: copy the DDG Control dashboard EXACTLY (Social footprint FOLLOWERS / VIEWS / LIKES, and the Company all-time row EXPENSES / GROSS REVENUE / DEBT / CHARITY DEDUCTED / NET PROFIT), same values, same labels, same signs. Never compute own totals, never reuse a figure from an older render, push, or memory.
  - Platform stats, finance figures, dates, prices, claims and citation cards: check against the live source or a cited article opened this session.
- Log every on-screen number with its source and check time in plan/numbers_check.md (value on screen, source value, source URL/screen, time, match yes/no).
- Preflight gate G0 NUMBERS: fails if any on-screen number is missing from numbers_check.md or doesn't match. Pull a frame of the HUD and compare it to the source before sending anything.
- If the source can't be read, show "—" / "No data" and say so to Markus; never guess.
- Lesson (21 Nov 2026): the Ep2 HUD showed 752 followers / 6,712 YT views (own sum + YouTube-only) while Control showed 811 / 108.4K / 435. Markus caught it. Never again.

## Every product, service, company or app he names gets shown on screen (RULE, Markus 23 Nov 2026, t269u: "I specifically asked you last time")
- Whenever Markus talks about a product, service, company, app or platform, bring it on screen while he talks about it: a framed screenshot pop-up, a scroll through their official webpage or product page, or the product itself (desktop frame for sites, phone mock-up for mobile/social). Official logo or name plus URL credit; Night Glass frame; above the webcam for the 9:16 crop; stays up for the topic span (>=10 s); blur rules still apply (private businesses of his stay hidden unless Markus says otherwise).
- Use the brand's OFFICIAL spelling on screen even when he or the ASR says it differently (e.g. the label printer he calls "Mynbyn" is MUNBYN, munbyn.com).
- Check: before every edit, run a mentions audit over the transcript (brand/product regex + capitalised-token scan, ASR variants mapped) and produce a table: name, every timestamp, on screen yes/no, planned visual. Preflight gate G11 MENTIONS fails if any named product/company has no on-screen visual (analogies like "Ferrari vs Toyota" may be a small chip; Markus decides on skips).
- Lesson: Ep2 v1 never showed the MUNBYN printer at ~4:50 even though Markus held it up and praised it.

## No small dead-air cuts inside the talk (RULE, Markus 23 Nov 2026, t262u + t270u)
- Do NOT trim short pauses/word gaps in the episode body; they look weird and v1's gap-trims clipped words. Play his talk continuously.
- Only genuinely long non-talking stretches (webcam moves, coffee-sip refresh waits, loading waits, phone interruptions, multi-second fumbles) are cut, and only after Markus picks them from a list with timestamps. Every cut boundary sits inside measured silence (10 ms RMS) with 100-150 ms padding and 20-40 ms fades.
- Check: preflight gate G10 CUTS (no boundary inside a word, RMS at each boundary near the noise floor); script /workspace/deepdive-ep2/v3fx/cutaudit.py.

## Audit adoption (Markus t278u, 23 Nov 2026): six standing changes
1. **Overlay priority.** When elements compete for space or time: (1) his face and voice, (2) the thing he is talking about (his screen, the product, the page), (3) energy edits, (4) commentary (Freya captions, fun facts), then drop the rest. A lower item never covers a higher one; if it can't fit, it moves or goes.
2. **Long-form pacing (~2 h deep-dives).** Chapter cards at each agenda change plus a re-hook every 5-8 min (a punch-in + kinetic pill or a "coming up" line on the next payoff). The persistent tracker and the "commentary every 30-60 s" rules are only for ~20-min vlogs.
3. **Spoken numbers as commentary/quotes.** A number he says that can't be verified against Control or a live source is never shown as a stat. Show it as context/commentary that is literally true, e.g. "$3,100 in 4 days" shows as: the trading bot made $3,100 in PAPER (fake) money, receipts visible on the dashboard in long form (the dashboard is cut off in Shorts, so the commentary must stand alone). The HARD GATE number rule still applies to every stat.
4. **Minimum durations.** 4.5 s (quick pop-ups) and 15 s (text-heavy) minimums are for long form only. Shorts use quicker beats: chips/pills 1.2-3 s, text cards just long enough to read twice.
5. **Hook/payoff rules.**
   - First 30 seconds: state the promise (what the viewer gets) and make sure the video pays it off; check both before render.
   - Thumbnail + title work as one: one idea, the title doesn't repeat the thumbnail text, both promise the same payoff (thumbnail-rules.md).
   - Shorts: target 20-45 s; longer only if the hook earns it (OpusClip-ranked 90+ and a complete story). End loop-friendly: the last line should flow back into the first.
6. **Post-upload retention review.** 48 h and 7 days after upload, read YouTube Studio retention: % at 30 s, % at 1 min, and every drop-off over ~5% in a minute. Log the moment and the likely cause in feedback-log.md and turn repeat causes into playbook rules.

## Shorts and placement rules (Markus t274u/t278u, 23 Nov 2026)
- **Captions never on his face.** Put them in empty space (top or middle of the screen panel), moving only when needed; check against the tracked face box every frame.
- **Clips over ~1 min open with a hook pulled from later in the clip** (e.g. the forex reel opens on "$3,100 in the few days since it started", shown with the paper-money commentary), then cut back to the start.
- **Novel cover.** Whenever he talks about his novel (Threads of Empire), show the cover photo on screen as a hook (asset: /workspace/vlog/ep1_reshoot/v3assets/threads_of_empire_cover.png).
- **Shorts get the full blur pass**, same rules as long form: private app/business names (e.g. Hypest), Replit URLs/@handles, ddg-control domains, private finances, account details, emails, keys. City/state level (Brisbane/QLD) is fine. Never blur over the webcam.
- **Placement in the main edit (so Shorts need no re-layout):** quick fun animations, chips and kinetic pills go ABOVE the webcam (left column over the cam), deep content (site scrolls, info cards, the novel cover) goes on the RIGHT. The 9:16 crop takes the webcam + the band above it.
- Swears censored in Shorts too (soft static + TV icon at 0.65 scale over the mouth, masked caption word); loudness -14 LUFS.

## OpusClip workflow (Markus, 23 Nov 2026; Pro plan, account info@digitaldynamics-group.com)
- **OpusClip does:** moment discovery and ranking (virality score + hook/coherence/connection/trend), a second transcript with word timings to cross-check our ASR, and hook scoring for teaser/Shorts candidates.
- **Our pipeline does everything that ships:** Night Glass styling, blur, censor, mentions pop-ups, numbers vs Control, captions off face, preflight. Cut points are always re-placed in our 10 ms measured silence (OpusClip cuts on word boundaries, ±0.1-0.3 s, 14/48 Ep2 in-points were <80 ms after the previous word).
- **Credits:** 1 credit per source minute. Check `opusclip_get_usage` before EVERY submit (261 left after Ep2 on 23 Nov 2026) and say the cost first if it's over ~140.
- Upload the raw source so times map to raw; private project; analysis only.
- `list_clips` has no start/end times: map clips with /workspace/ddg-video-toolkit/opusclip/mapclips.py (matches each clip transcript to the word-timed project transcript, then raw -> master time).
- **Never publish, schedule or share OpusClip's raw output** and never use its posting tools; its clips have no blur or censor.


## PART 2: Saved editing rules (memory, not all duplicated above)
- Captions in Shorts never cover his face; place in empty space (top/middle of screen panel). Clips over ~1 min open with a hook line pulled from later in the clip. (23 Nov)
- OpusClip (Pro, info@digitaldynamics-group.com) is the priority tool for moment discovery, clip ranking and hook scoring; send its recommendations for approval before implementing; our pipeline adds Night Glass styling, blur, censoring, mentions and number checks. Spoken figures like the trading bot's $3,100 show as commentary noting it's paper money. (23 Nov)
- Before implementing OpusClip or other edit recommendations, send recommendations (and sample snippets before a full render) and wait for his pick. (22 Nov)
- Edits match his on-camera energy: tasteful shake, punch-in zooms, speed ramps, impact flashes, SFX hits, kinetic captions on energetic moments; never obnoxious. Teaser hooks fun/catchy; every clip cut on word boundaries. (23 Nov)
- After the intro, show the full episode agenda for the first 30 s, then collapse to the next six items. (22 Nov)
- No YouTube AI/synthetic disclosure on DDG Shorts; keep "Made with AI tools" in description. (31 Oct)
- Novel mentions: show Threads of Empire cover as a hook, release date TBD. Shorts get the same full privacy blur as long form. (23 Nov)
- Never make small dead-air/pause cuts; only propose cutting long non-talking gaps for his decision. (23 Nov)
- Blurs stay constant for the whole span and fully cover the target; never flickering per-frame OCR boxes. (24 Nov)
- Every product/service/company mentioned goes on screen at that moment (logo + screenshot/pop-up or site scroll). (23 Nov)
- Blurs are tight rounded boxes only over private details; overlapping blurs merge; strength ~40% lower than early default; window blur fits exactly to the white frames. (21 Nov)
- AI platforms he uses (Replit, Claude, Grok Bot, Antigravity etc.) get cut-out logo + researched key features for the segment; private URLs/account details still blurred. (20-21 Nov)
- Official DDG intro/outro animations always used as supplied; never speed up his speech in Shorts; snap zooms ~30% smaller; no robot emojis; Night Glass branding. (30 Oct)
- "Edit" callouts use Ep1-style motion graphics intensifying each time (~400%), white streaks, no big blue circle. (21 Nov)
- Pop-ups readable, grid-snapped, stay up for the whole topic; past episode references show thumbnail + YouTube link; dog mentions cut in Maisy park footage; no fact-check cards on obvious exaggeration/rants. (11-12 Nov)
- Covers: expressive-face frame, hook text visible, sharp and flattering, never mid-blink; he sees them before use. (30 Oct)
- Deep dives work for screen-free listening; research off-looking spoken figures and ask if he's joking. (30-31 Oct)
- Never post/upload/schedule anything without his final go.
- Bot renamed Freya -> Marketing (24 Nov).

## PART 3: Marketing-mode company rules
# DDG Marketing-Mode Rules (from 29 Oct 2026, approved by Markus)

For the next 3 to 5 months DDG runs bare-minimum operations, and about 90% of usage goes to marketing. These rules are the whole policy. The old skills are archived at /workspace/archive/skills-2026-10-29.

## Lineup
- **Freya (Marketing Director):** DDG marketing. YouTube (vlogs and Shorts) is the core channel, X feeds it, Instagram gets reposted Shorts only. She also covers gaming clips, music as content, and the Threads of Empire book launch (end of Jan 2027).
- **Tyr (CDC Venture Manager):** Cattle Dog Coffee marketing and sales. That covers the Christmas sale to Fri 11 Dec, B2B gifting emails, Shopify and CDC socials. No PM or RAID work.
- **Heimdall (GM/COO):** the 7:00am weekday list to Markus, the Monday 9:00am review (10 lines or fewer), and anything else only on request.
- **Paused:** Mímir, Njord, Daedalus, Harald, Hermes and Plutus have no routines. They act only if Markus messages them directly.
- **DDG Finance:** Claude has full authority. Bots don't touch trading.

## Non-negotiables
1. **No spend** beyond Cursor Pro+, Replit, Claude and the Grok Bot plan without Markus's Yes.
2. **Nothing goes out** (email, post, DM or reply) without Markus's Yes, except schedules he has already approved. Gmail is drafts only, and Markus presses Send.
3. **No invented facts or numbers.** Cite the source, or label it PROJECTED or UNVERIFIED. Look numbers up online rather than asking Markus.
4. **DDG and CDC marketing stay separate:** separate accounts, branding and strategy. DDG vlogs may name and show CDC.
5. **Usage:**
   - Essential words only.
   - In group chats, only the bot addressed replies.
   - Edit in place.
   - No cloud agents without a Yes.
   - No new routines without Markus's Yes.
6. **Security:** least privilege and no new credentials. Any key or account incident goes straight to Markus and Claude.
7. **Legal:**
   - CDC emails follow the Spam Act: consent, sender ID and an unsubscribe line.
   - **YouTube AI label (changed by Markus, 31 Oct 2026):** do NOT turn on YouTube's AI / altered-or-synthetic disclosure for DDG videos. The footage is real Markus; only the editing uses AI. Keep the description line "Made with AI tools." The only exception is a video with an AI-cloned voice or AI-generated realistic footage, which YouTube policy requires to be labelled; ask Markus first.
   - Use the wording "charities like the RSPCA".
8. **One daily list to Markus:** all asks go through Heimdall's 7:00am list. Keep it to 5 points or fewer, and every ask carries a recommendation.
9. **Tone:** light banter with each other and with Markus is fine. Never call him "Gaffer".
10. **Track results:** keep a short running log of what worked, what didn't and any pivots, for the playbook. Record it in shared journal memory, not in new trackers.
11. **Timing:**
    - Every routine runs EXACTLY on :00, :15, :30 or :45 (exact timing, never flexible). Round any time to the nearest 15 minutes.
    - No failure-notice emails or extra reminders to Markus. Report failures only in the bot's normal daily list.

12. **Personal touch (Markus, 29 Oct 2026):** DDG socials should feel like following a person and creator, not a cold company. Markus's own photo (the smiling, head-tilted Ep1 thumbnail shot, with a privacy-safe background) is the profile picture on every DDG platform instead of the logo. Captions, replies and bios use a warm, first-person, personality-led voice while staying professional. Keep names short: "Digital Dynamics" first, and "Digital Dynamics Group" only if needed.

## Review
The first review is Mon 30 Nov 2026: usage by bot, plus one result number per channel. The next is after the book launch, in early Feb 2027.
