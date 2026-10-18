# The Stage

Ask something worth seeing and your agent shows it as it answers. "Where are the hottest places on
earth?" puts them on a world map. "How does the market behave when volatility is low?" gets a chart and
the chain of cause and effect. The written answer still comes too. The Stage plays the story next to it.

## What it can show

| Scene | What it is for |
|---|---|
| Chart | A trend, a comparison or a share: line, area, bar, scatter or pie, with lines called out ("low IV below 12") |
| Map | Places (dots sized by their value) and countries (shaded by their value), on a world map that works offline |
| Numbers | Three to six key figures, counted up |
| Timeline | Events in order |
| Steps | A chain: this leads to that |
| Table | Rows and columns |
| Picture | A photo, a diagram or an image the agent made, slowly moving |
| Video | A YouTube video, such as a tutorial, played on the Stage |
| Film | A short 3D animation, such as a rocket launch, a city growing or revenue rising, played from a shot list |

Every scene with numbers says where they came from, or says "Illustrative, not data" when it is an
example. A scene the agent can't back with a source is refused until it names one or says it is an
example.

## Films

For something that moves, grows or gets built, the agent can make a film: three to six shots of two to
eight seconds, each a subject and a camera move with the line said over it. The subjects are a city, a
tower, bars, a rocket, a factory, solar panels, a road, a conveyor, a crowd and a globe. The camera can
orbit, push in, rise, fly across or look down. The light is day, dusk or night.

The agent writes the shot list and your screen builds the scene, so nothing the agent wrote runs as code.
Bars, a tower's height and a crowd's size are numbers, and need a source like a chart. The agent decides
how big an answer deserves: no scenes for a plain fact, a chart for a comparison, and at most one film,
at the start or the end of a big story.

![A film on the Stage, shot 3 of 4: four 3D bars rising for revenue in years one to four, each labelled with its value, and the line "Revenue climbs year on year" over the picture](screenshots/stage-film.png)

Without 3D graphics, with reduced motion on, and on your phone, a film is a storyboard: one card per
shot with its line.

![The same film on a phone with reduced motion: a storyboard of cards, "1 · 5s · push, It starts in one small building" and "2 · 5s · orbit, 1,000, The first thousand customers find it"](screenshots/stage-film-storyboard.png)

## Watching a story

The Now tab is a dark room. Each scene fills it: a title, the drawing, and the narrator's line underneath like
a subtitle. ▶ plays the story from the start (read aloud when voice replies are on), ‹ and › step through it,
and the bars at the top show where you are.

- **♪** plays a soft background score made on your screen. It is off until you turn it on, and stops when the
  Stage closes.
- **⤵ Go deeper** asks for that scene as its own story. It is sent in the same chat, plays here next, and
  **↖ Back** returns to where it came from. A scene you went deeper on shows its deeper story in the bar.
- **Versions**: ask in the chat to change what is on the Stage ("add Japan", "use this year's figures") and
  the agent shows the whole story again. The version before stays, one tap away at the top right.
- **⛶** makes it full screen.

## Answer BIG

On by default. The agent shows answers that have numbers, places, a trend or a story, two to five
scenes in order, without being asked. A plain question still gets a plain answer.

Off, it shows something only when you ask to see it. Switch it in the Stage, in Settings → Appearance,
or with `bento stage big on|off`.

## Where it plays

- **The Stage app** opens by itself when a scene arrives for the chat on your screen (Chat, the
  Office's chat, or the prompt bar). Turn "Open by itself on this screen" off under Boards if you'd
  rather open it yourself.
- **Chat** puts a ▶ Play chip under each answer that has a story, also when you reopen the chat later.
- **Telegram** gets the story first, then the words: one album, a picture per scene, with the question on
  top and each scene's title, takeaway and source under it. A map lists what happened at each place, numbered
  on the map and written out under it, so a phone sees the notes a desk sees on hover. With a speech engine
  on this machine (Settings → Voice: ElevenLabs, OpenAI, Google, Piper…), the story follows as one audio
  message, told in your agent's voice; the browser voice can't, because it lives in a browser
  (`telegram.narrate: false` turns it off). A video scene follows as its YouTube link, which Telegram plays
  in place. The pictures are drawn by the Stage's own code in a headless Chromium on this machine. With no
  Chromium here, the story goes as one page instead. **WhatsApp** gets the same pictures, one at a time.

  ![A news map on Telegram: five numbered places, each with what happened there listed under the map](screenshots/stage-telegram-map-notes.png)
- **A terminal** prints each scene as text: a chart as a sparkline or bars, a map as its places. The TUI
  and the terminal chat print them as they arrive; `bento stage` shows the last chat's story, `bento stage
  list` everything.

## Your stories are kept

Every story stays with its chat. The Stage's **Library** lists everything you've been shown, newest
first, by the question you asked.

**★ Keep** makes a story a **board**. A board can stay as it is, or ask its question again every hour,
day or week: the agent looks the facts up afresh and shows the new story, and the board points at it.
If a refresh shows nothing, the board keeps the last story and says why. Refreshes are listed in
Missions → History. With nobody watching, a refresh can show scenes and look things up; anything that
needs your yes is refused, as for any scheduled run.

## Your own app instead

Under Boards, **Show answers in** can name one of your apps. That app receives each scene and the Stage
stays closed. In the app:

```js
window.addEventListener('appstage', e => draw(e.detail.scene));
```

`e.detail.scene.kind` is one of `chart`, `map`, `numbers`, `timeline`, `steps` or `table`, with the
same fields the agent's `show_scene` tool takes. App Studio knows this: ask it for "an app that draws my
Stage".

## For developers

- `agentos/stage.py` reads each scene field by field (`clean`), files it under the person's message it
  answers, keeps boards, and builds the Telegram page (`report_html`). It has no HTTP or asyncio.
- `show_scene` is a safe tool: it draws on the person's own screen and stores a row. The conversation is
  injected by the agent loop, never chosen by the model. A forwarded Claude Code chat reaches it through
  the team door (`mcp__bento__show_scene`).
- `24l-stage.js` draws everything with text nodes and SVG, never markup, because a scene's words are
  often a web page's. The map is Natural Earth's 1:110m countries (public domain), loaded the first time
  a map is drawn.
