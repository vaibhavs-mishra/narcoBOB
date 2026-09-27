# Problem Statement

## Background

Punjab sits on a major trafficking route for heroin and synthetic opioids crossing the
international border, and it carries one of India's heaviest drug burdens:

- India's national survey found that **2.06% of Indians (10–75 years) currently use
  opioids**, and that about **60 lakh people have opioid use disorders**. More than half of
  them are in a handful of states that include **Punjab**, and by share of the population
  Punjab is among the most affected states in the country.
  ([NDDTC–AIIMS, *Magnitude of Substance Use in India*, press release, PIB, 18 Feb 2019](http://pib.nic.in/newsite/PrintRelease.aspx?relid=188688))
- In 2021, Punjab registered **9,972 cases under the NDPS Act**, third in absolute
  numbers, but with the **highest rate in India: 32.8 cases per lakh population**.
  ([NCRB *Crime in India 2021*, reported by The Tribune, 1 Sep 2022](https://www.tribuneindia.com/news/punjab/ncrb-report-punjab-third-in-country-in-ndps-cases-but-rate-per-lakh-highest-427254))

These two sources are also what our simulated event stream is calibrated against in spirit
(overdoses concentrated around urban centres, enforcement concentrated around police
stations). No figure in the running system is presented as real data.

## The Problem

District narcotics intelligence is **reactive and enforcement-biased**:

1. **Signals sit in silos.** Seizures and arrests live in police records, overdose
   admissions in hospital registers. They are rarely joined, and usually reviewed monthly.
2. **Enforcement counts are read as drug activity.** A high seizure count often measures
   *where police are active*, not where drugs are spreading. A one-day raid looks like a
   hotspot; a new supply route in a lightly policed village looks like nothing.
3. **There is no early warning for *emerging* hotspots.** By the time a new route shows up
   in seizure statistics, it has been harming people for weeks.
4. **Automated flags are not trustworthy on their own.** Small numbers, a hospital that
   stopped reporting for three days, or a statistical quirk can all look like a spike.
   An officer who acts on a false alarm spends scarce resources in the wrong place, and
   one who is flooded with false alarms stops listening.

## Who is Affected

- **Primary:** a district or zone narcotics intelligence officer (SSP/DSP-level analyst)
  who must decide where to deploy interdiction and why, and defend that decision.
- **Secondary:** a district health officer planning de-addiction capacity, naloxone and
  awareness programmes, who needs the same early warning from the harm side.
- **Indirectly:** communities where a new supply route is taking hold, who pay for every
  week of delay in overdoses and addiction.

## Why It Matters

Every week between a new supply route opening and a response arriving is measured in
overdoses. An early, *explainable* warning, one an officer can check and defend, turns
a monthly retrospective into a same-week response, and points it at the right place:
enforcement at the supply, treatment for the people already affected.

## Why Existing Solutions Fall Short

| Approach | Why it is not enough |
|---|---|
| Monthly review of seizure/arrest statistics | Too slow, and it measures police activity rather than drug harm; a raid looks like a hotspot |
| Ranking areas by raw counts | Always names the busiest areas; cannot distinguish an *escalating* area from a permanently busy one. In our backtest a raw ranking produces ~53 new "top-5 hotspots" a month on a calm map |
| Kernel-density "hotspot maps" | Show where things *have been*, not where they are accelerating; no notion of evidence quality |
| Black-box ML risk models | Hard to explain or defend; need labelled data that does not exist; risk encoding enforcement bias as "risk" |
| An LLM reading the data | Not reproducible, can invent numbers, cannot be audited |

NarcoBob's answer is to separate the two jobs: a deterministic statistical engine does all
the math (fast, explainable, reproducible), and IBM Bob agents do the judgment and the
writing, including an adversarial **Skeptic** whose job is to break weak alerts before they
reach an officer. See [solution-overview.md](solution-overview.md).
