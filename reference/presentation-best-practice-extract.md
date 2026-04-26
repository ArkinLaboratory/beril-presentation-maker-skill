# Presentation best-practice extract for beril-presentation-maker

Sources read (live-fetched 2026-04-26 from the URLs Adam supplied):

1. **Naegle 2021** — Naegle KM. *Ten simple rules for effective
   presentation slides.* PLoS Comput Biol 17(12): e1009554.
   doi: [10.1371/journal.pcbi.1009554](https://doi.org/10.1371/journal.pcbi.1009554)
   PMC: PMC8638955.
2. **Bourne 2007** (republished by UVa Chemistry) — Bourne PE. *Ten
   Simple Rules for Making Good Oral Presentations.* PLoS Comput Biol
   3(4): e77. doi:10.1371/journal.pcbi.0030077. Mirror:
   https://chemistry.as.virginia.edu/how-prepare-and-present-scientific-talk
3. **Ross et al. 2007** — *Giving a Good Scientific Presentation.*
   Prepared for the American Society of Primatologists by members of
   the ASP Education Committee. PDF: https://www.asp.org/education/EffectivePresentations.pdf

This document extracts the rules, claims, and prescriptions from
these sources that informed SPEC §6 (slide-shape vocabulary), §6.1
(punchline titles), §6.3 (density discipline), §10 (speaker notes),
and §13 (validators P1–P10). Items not relevant to BERIL's typical
project shape are explicitly noted.

---

## 1. Naegle 2021 — Ten simple rules for effective presentation slides

### Rule 1 (quoted): Include only one idea per slide

> "Each slide should have one central objective to deliver—the main
> idea or question [3–5]."

**Informs SPEC §6.3** (max 5 content elements per slide; max 35 words
per slide) and **SPEC §6** layout vocabulary (each layout supports
exactly one focal element: one figure, one claim, one number, one
diagram).

### Rule 2 (quoted): Spend only 1 minute per slide

> "When you present your slide in the talk, it should take 1 minute
> or less to discuss."

**Informs SPEC §5** mode-specific slide budgets (talk-30: 25–32
slides; talk-15: 13–17; talk-45: 35–48; lightning-5: 5–8) and
**SPEC §13** validator P2 (time budget = slide_count × 1 min ± 20%).

### Rule 3 (quoted): Make use of your heading

> "When each slide conveys only one message, use the heading of that
> slide to write exactly the message you are trying to deliver."

**Informs SPEC §6.1** (punchline titles): titles are the slide's
message, not its topic. Validator P-titles flags topic-style titles
("Methods", "Results", "Background", "Workflow", "Approach",
"Overview").

### Rule 4 (quoted): Include only essential points

> "While you are speaking, audience members' eyes and minds will be
> wandering over your slide."

**Informs SPEC §6.3** density discipline. Speaker notes carry the
non-essential context (SPEC §10) so the slide stays clean.

### Rule 5 (quoted): Give credit, where credit is due

> "An exception to Rule 4 is to include proper citations or
> references to work on your slide."

**Informs SPEC §9** citation discipline. Short-form on-slide
("Smith 2023"), full citation in speaker notes and on the references
slide.

### Rule 6 (quoted): Use graphics effectively

> "As a rule, you should almost never have slides that only contain
> text."

**Informs SPEC §6** layout vocabulary: every content layout has at
least one image/diagram slot (`claim_evidence` figure,
`workflow_diagram` diagram, `data_figure` chart, `concept_illustration`
image, `big_number` numeric typeset) except `methods_summary`,
`acknowledgments`, and `references` (where graphic-free is
conventional).

### Rule 7 (quoted): Design to avoid cognitive overload

> "The type of slide elements, the number of them, and how you
> present them all impact the ability for the audience to intake,
> organize, and remember the content."

**Informs SPEC §6.3** max-elements rule (5 content elements per slide)
and validator P10.

### Rule 8 (quoted): Design the slide so that a distracted person gets the main takeaway

> "It is very difficult to stay focused on a presentation, especially
> if it is long or if it is part of a longer series of talks at a
> conference."

**Informs SPEC §6.1** (punchline-as-title) — even a distracted
audience member who reads only the title should leave with the slide's
message.

### Rule 9 (quoted): Iteratively improve slide design through practice

> "Well-designed slides that follow the first 8 rules are intended to
> help you deliver the message you intend and in the amount of time
> you intend to deliver it in."

**Informs SPEC §16.5** `revise` verb. Iterative refinement is a
first-class feature.

### Rule 10 (quoted): Design to mitigate the impact of technical disasters

> "The real presentation almost never goes as we planned in our heads
> or during our practice."

Out of v1 scope. The skill produces .pptx (and optionally .pdf); the
robustness-against-technical-failure work belongs to the presenter,
not the drafter.

---

## 2. Bourne 2007 — Ten Simple Rules for Making Good Oral Presentations

This is the older sister paper to Naegle 2021. UVa republishes it as
the "How to Prepare and Present a Scientific Talk" page that Adam
cited.

### Rule 1 (quoted): Talk to the Audience

> "We mean prepare presentations that address the target audience.
> Be sure you know who your audience is—what are their backgrounds
> and knowledge level of the material you are presenting and what
> they are hoping to get out of the presentation?"

**Informs SPEC §1.3** (peer-only audience for v1; lay/program-officer/
executive in v1.x) and **SPEC §3.1** tier-aware language conservatism.

### Rule 2 (quoted): Less is More

> "A common mistake of inexperienced presenters is to try to say too
> much. ... A side effect of too much material is that you talk too
> quickly, another ingredient of a lost message."

**Informs SPEC §4.2.1** mode-capacity overflow: the skill halts when
too much content is forced into too few slides; user picks (D-027).

### Rule 3 (quoted): Only Talk When You Have Something to Say

> "Do not be overzealous about what you think you will have available
> to present when the time comes. ... Remember the audience's time is
> precious and should not be abused by presentation of uninteresting
> preliminary material."

**Informs SPEC §3.1** EXPLORATORY tier handling. The skill flags
EXPLORATORY-tier projects with a "this is hypothesis-generating, not
confirmatory" caveat; speaker notes carry the explicit framing.

### Rule 4 (quoted): Make the Take-Home Message Persistent

> "A good rule of thumb would seem to be that if you ask a member of
> the audience a week later about your presentation, they should be
> able to remember three points."

**Informs SPEC §6.2** big_idea slides at substory transitions and
**§6** `implications` layout. The deck has three persistence anchors:
the meta-arc (one sentence on `big_idea`), each substory's punchline
(on `section_divider`), and the implications slide (3 bullets max).

### Rule 5 (quoted): Be Logical

> "Think of the presentation as a story. There is a logical flow—a
> clear beginning, middle, and an end."

**Informs SPEC §4** throughline-meta-arc gate and **§6** divider-slide
discipline. The throughline is the spine; substories are the chapters.

### Rule 7 (quoted): Practice and Time Your Presentation

> "An important talk should not be given for the first time to an
> audience of peers. You should have delivered it to your research
> collaborators who will be kinder and gentler but still point out
> obvious discrepancies."

**Informs SPEC §11** Q&A prep deliverable: the speaker rehearses
against the 10 anticipated questions before the real audience.

### Rule 8 (quoted): Use Visuals Sparingly but Effectively

> "Some can captivate the audience with no visuals (rare); others
> require visual cues..."

**Informs SPEC §8** figure handling tiers. Sparingly = max 2 figures
per slide (P10), curated subset of 4–10 figures from a typical 30+
project figure set.

### Rules 6, 9, 10 (Treat Floor as Stage / Practice Q&A / End Strong)

Out of v1 scope — these are presenter behaviors, not deck content.
Speaker notes section "transition lines" (SPEC §10.2) cover the
end-strong concern at slide level.

---

## 3. Ross et al. 2007 (ASP) — Giving a Good Scientific Presentation

The ASP guide is more practical than rule-based. Key prescriptions
(quoted from the PDF, which is unpaginated; section names cited):

### Part 1: When to do an oral vs. a poster presentation (quoted)

> "Oral presentations are challenging to design and execute
> effectively. One of the greatest obstacles is the strict time limit.
> For many sessions, each speaker is allowed just 15 minutes, which
> must include time for introduction and questions, leaving the
> speaker no more than 12 minutes to present the work."

**Informs SPEC §5** mode dispatch — `talk-15` mode is the
ASP-canonical talk shape (12 minutes content + 3 Q&A).

> "If your materials (e.g., your methods or the results) are
> especially complicated, it may be a better idea to present them in
> a poster, where your colleagues will be able to take their time..."

**Informs SPEC §12** poster mode — posters are for content that
exceeds the talk's pacing budget, and the maker treats them as a
separate render path, not a 1-slide deck.

### Common ASP recommendations relevant to v0.1

The ASP guide additionally argues for:

- **Title slide with affiliation, funder, and date.** SPEC §6
  `title` layout matches.
- **Acknowledgment slide near the end.** SPEC §6 `acknowledgments`
  layout matches.
- **Plain-language conclusions.** SPEC §6 `implications` layout +
  audience-tier prompt language matches.
- **Avoid jargon early.** SPEC §3.1 tier-aware language conservatism
  applies; v1 audience is peer (jargon allowed) but the prompt still
  flags excessive jargon density on opening slides.

---

## 4. Cross-cutting prescriptions adopted into SPEC

| SPEC section | Source rule(s) |
|---|---|
| §1.3 audience targeting | Bourne Rule 1 (Talk to the Audience) |
| §3.1 tier-aware language | Bourne Rule 1, Bourne Rule 3 |
| §4 throughline gate | Bourne Rule 5 (Be Logical) |
| §4.2 substory clustering | Naegle Rule 1 (One idea/slide), Bourne Rule 4 (Take-Home Message) |
| §4.2.1 mode-capacity overflow | Bourne Rule 2 (Less is More) |
| §5 mode budgets | Naegle Rule 2 (1 min/slide), Ross 2007 Part 1 |
| §6 layout vocabulary | Naegle Rules 1, 6 (Graphics Effectively), 8 (Distracted-Reader Test) |
| §6.1 punchline titles | Naegle Rule 3 (Use Your Heading), Rule 8 |
| §6.2 big-idea at transitions | Bourne Rule 4 (Take-Home Message), Bourne Rule 5 |
| §6.3 density discipline | Naegle Rule 4, Rule 7, Bourne Rule 8 |
| §8 figure handling tiers | Naegle Rule 6, Bourne Rule 8 |
| §9 citation on-slide short-form | Naegle Rule 5 |
| §10 speaker notes | Naegle Rule 4 (Essential Points) — non-essential context goes here |
| §11 Q&A prep | Bourne Rule 7 (Practice) |
| §12 poster render path | Ross 2007 Part 1 |
| §13 validators P1, P2, P10, P-titles | Naegle Rules 1, 2, 3, 7 |
| §16.5 revise verb | Naegle Rule 9 (Iterative Improvement) |

---

## 5. Items the skill explicitly does NOT enforce

- **Animation, transitions, builds.** Naegle 2021 doesn't address;
  Bourne is silent. v1 produces static slides.
- **Color schemes beyond contrast.** KBase brand is the only color
  system v1 supports (D-015); presenters who want a different palette
  edit the .pptx directly.
- **Live demo integration.** Out of scope.
- **Presentation room / projector compensation.** Out of scope (Naegle
  Rule 10 is the presenter's, not the drafter's).
- **Body language / vocal delivery.** Out of scope (Bourne Rules 6, 9,
  10).

---

## 6. Open questions for v1.x

1. **Poster pacing.** Ross 2007 Part 1 argues posters fit
   methodologically complex work; we have not validated whether the
   maker's poster output preserves that property when content is
   compressed from a 30-min talk.
2. **Distracted-reader test (Naegle Rule 8) as a validator.** v1
   enforces punchline titles (P-titles) but does not run a "does the
   title alone convey the message?" check. Could add as P-titles-v2.
3. **Iterative-improvement metric (Naegle Rule 9).** v1 supports
   `revise` mechanically but doesn't track cross-revision quality.
   Atlas-style sophistication scoring on the deck is v1.x.
