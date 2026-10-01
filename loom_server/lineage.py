"""Works and how they descend from one another.

A source record answers "what page did we read". That is not the same as "what work is this, who made it, and what
earlier work does it extend or correct". This module keeps the second question separately, because the owner's
requirement is a branching lineage of real works with locator-bearing evidence, not a sentence a model wrote.

Three questions are kept apart and never merged:
  * origin        — who first published this contribution, and when
  * implementation — what the current official version or maintained implementation is
  * validity      — whether it still holds today

A work gets a stable identifier, so the same work found twice through different pages is one work and an edge
between two works survives re-running research. An edge is `supported` only when a locator points into a work
whose own identity rests on text Loom retrieved itself; a secondary summary can point at an original but can never
become the evidence for it. Anything unestablished stays `unknown` or `disputed`, never quietly supported.
"""
from __future__ import annotations

import hashlib
import re

RELATIONS = ("introduced", "documented", "extended", "corrected", "replicated", "applied", "superseded")
# What each relation says about the EARLIER work. Only these three are claims of descent from an original.
DESCENT = ("extended", "corrected", "replicated")
ORIGIN_STATUS = ("established", "unknown", "disputed")
# `unresolved` is not a weaker kind of support. It says two runs of the review gave different answers to the SAME
# question on the SAME evidence and nobody has decided between them. Until a person decides on the evidence, the
# claim has no standing at all: it is not supported, and it is not merely unknown either, because something IS
# known about it — that the review contradicted itself.
EDGE_STATUS = ("supported", "unresolved", "unknown", "disputed")
# Lower is more cautious. A disputed reading of an assertion always wins the merge; above it, better support wins.
# An unresolved disagreement sits just above disputed: it outranks both `unknown` and `supported`, so one record
# of an assertion carrying a live contradiction cannot be covered up by another record that happens to look clean.
_RANK = {"disputed": 0, "unresolved": 1, "unknown": 2, "supported": 3}
# Findings, not absences. Neither can be displaced by a better-looking reading of the same assertion: a rejection
# stands, and so does a contradiction nobody has settled.
_STICKY = ("disputed", "unresolved")

# Aspects of a judgement that belong to the SOURCE, so a contradiction in any of them unsettles every relationship
# read from that source. A contradiction about one relationship is NOT one of these: it unsettles that
# relationship alone and leaves the other claims on the same page exactly where they were.
SOURCE_WIDE_ASPECTS = ("identity", "role", "overall", "lineage_supported")


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "").strip().lower())


def _norm_identifier(idf) -> str:
    """A DOI, ISBN, arXiv id or address reduced to one comparable form."""
    t = _norm(idf)
    t = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "doi:", t)
    t = re.sub(r"^info:doi/", "doi:", t)
    t = re.sub(r"^urn:isbn:", "isbn:", t)
    t = re.sub(r"^arxiv\.org/abs/", "arxiv:", t)
    t = t.rstrip("/.")
    return re.sub(r"[\s-]+", "", t) if t.startswith(("doi:", "isbn:", "arxiv:")) else t


def work_id(w: dict) -> str:
    """A stable identifier for one work.

    A published identifier decides it, so the same work reached through two different pages is one work. With no
    identifier the title, first creator and date decide it. The address is used only as a last resort, because a
    work is not its URL: the same paper sits at several addresses.
    """
    idf = _norm_identifier(w.get("identifier"))
    if idf:
        return "w:" + hashlib.sha256(idf.encode("utf-8")).hexdigest()[:16]
    creators = w.get("creators") or w.get("authors") or []
    first = _norm(creators[0] if isinstance(creators, list) and creators else creators)
    seed = "|".join([_norm(w.get("title")), first, _norm(w.get("published"))])
    if seed.strip("|"):
        return "w:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return "w:" + hashlib.sha256(_norm(w.get("url")).encode("utf-8")).hexdigest()[:16]


def _retrieved_itself(s: dict) -> bool:
    """Whether Loom's own retrieval found this source's quotation in the page, verbatim."""
    d = s.get("directRetrieval") or {}
    return bool(s.get("evidenceLevel") == "direct_text_quote_found" and d.get("quoteVerbatim") and d.get("sha256"))


# Where a published identifier can be resolved to a public address that serves the work itself. A DOI is resolved
# through the registry that issued it, an arXiv preprint through arXiv's own abstract page, and an RFC through the
# RFC Editor. An ISBN names a book and has no address that serves the text, so it is recognised and left alone
# rather than pointed at a shop or a library catalogue that is not the work.
_ID_FORMS = (
    ("doi", re.compile(r"""\b(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s"'<>,;]+)""", re.I),
     lambda v: "https://doi.org/" + v.rstrip(".,;)"), "doi:{v}"),
    ("arxiv", re.compile(r"\barxiv[:\s/]*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I),
     lambda v: "https://arxiv.org/abs/" + v, "arxiv:{v}"),
    ("rfc", re.compile(r"\brfc[\s-]?(\d{3,5})\b", re.I),
     lambda v: "https://www.rfc-editor.org/rfc/rfc" + v + ".txt", "rfc{v}"),
    ("isbn", re.compile(r"\bisbn[-\s:]*((?:97[89][-\s]?)?[\d][\d\-\s]{8,15}[\dxX])", re.I), None, "isbn:{v}"),
)


def named_work_address(named) -> dict | None:
    """The public address that serves a work named by its published identifier, or None.

    This is the far end of a relationship. A document that says it extends doi:10.12688/f1000research.3-62.v2 has
    named a work precisely enough to go and get; a document that says it extends "the computational notebook
    format" has named an idea, and no address will ever resolve it. Only the first kind is returned, so Loom
    fetches what a text actually identified and never guesses at what it meant.
    """
    t = str(named or "").strip()
    if not t:
        return None
    for kind, rx, to_url, ident in _ID_FORMS:
        m = rx.search(t)
        if not m:
            continue
        v = m.group(1).strip().rstrip(".,;)")
        got = {"kind": kind, "identifier": ident.format(v=re.sub(r"[-\s]", "", v) if kind == "isbn" else v),
               "url": to_url(v) if to_url else None}
        if not got["url"]:
            got["why_not_fetched"] = "An ISBN names a book, not an address that serves its text."
        return got
    return None


def ident_key(v) -> str:
    """One comparable form of a published identifier, whichever way a document wrote it down.

    A paper names its predecessor as "10.12688/f1000research.3-62.v2" and Loom fetched it as
    "doi:10.12688/f1000research.3-62.v2"; another names "RFC 2234" where Loom holds "rfc2234". Matching the two
    spellings as text left every fetched earlier work sitting beside the relationship that named it rather than on
    the end of it. Anything that is not a recognised identifier falls back to plain normalisation.
    """
    got = named_work_address(v)
    return got["identifier"] if got else _norm_identifier(v)


def _norm_address(u) -> str:
    """One spelling of an address, so a trailing slash does not split one document into two.

    The acceptance course holds the same PMC article twice, once with a trailing slash and once without, and
    grouping on the raw text kept them apart as two works.
    """
    import urllib.parse
    try:
        p = urllib.parse.urlsplit(str(u or "").strip())
    except ValueError:
        return _norm(u)
    if not p.netloc:
        return _norm(u)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{p.path.rstrip('/').lower()}" + (f"?{p.query}" if p.query else "")


def canonical_work_ids(sources: list) -> dict:
    """Source id -> work id, with several claims read from the SAME retrieved document treated as one work.

    A page carrying five claims produces five source records. Each became its own work whenever the titles
    recorded on them differed, so one document appeared in the graph as several works and one relationship read
    from it was counted once for every claim: the acceptance course showed one NOAA readme as three works.

    The same bytes at the same address are one document, and a document is one work. The exception is kept: where
    the records themselves name DIFFERENT published identifiers, the address really does hold more than one work,
    and those are left apart rather than merged into a single wrong one.
    """
    groups: dict = {}
    for s in sources or []:
        sha = (s.get("directRetrieval") or {}).get("sha256")
        if sha and s.get("id"):
            groups.setdefault((_norm_address(s.get("url")), sha), []).append(s)
    out: dict = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        if len({_norm_identifier(s.get("identifier")) for s in group if _norm_identifier(s.get("identifier"))}) > 1:
            continue
        # The most fully identified record names the work; ties fall to the lowest source id, so the answer does
        # not depend on the order research happened to return.
        rep = min(group, key=lambda s: (not _norm_identifier(s.get("identifier")), not s.get("authors"),
                                        not s.get("published"), not s.get("title"), str(s.get("id"))))
        wid = work_id(rep)
        for s in group:
            out[s["id"]] = wid
    return out


def work_from_source(s: dict, canonical: dict | None = None) -> dict:
    """The work a source record stands for, with the evidence that its identity rests on."""
    role = s.get("role") or "secondary_aid"
    w = {"id": (canonical or {}).get(s.get("id")) or work_id(s), "title": s.get("title"), "creators": s.get("authors") or [], "published": s.get("published"),
         "version_or_edition": s.get("version_or_edition"), "identifier": s.get("identifier"), "role": role,
         "seenAt": [s.get("url")] if s.get("url") else [], "fromSources": [s.get("id")] if s.get("id") else []}
    # An origin is established only when every one of these holds. A matched passage says a page contains those
    # words; it says nothing about who wrote the work or whether the work is where a contribution first appeared.
    why, disputed = [], False
    av = (s.get("attribution") or {})
    verdict = av.get("verdict") if isinstance(av, dict) else None
    raw_detail = av.get("detail") if isinstance(av, dict) else None
    # A detail that is not a mapping tells us nothing, and asking it questions used to raise. It fails closed.
    detail = raw_detail if isinstance(raw_detail, dict) else {}
    detail_unreadable = raw_detail is not None and not isinstance(raw_detail, dict)
    if role == "secondary_aid":
        why.append("this is a secondary aid, so it does not itself establish an origin")
    if role == "official_documentation":
        why.append("this is the current official documentation, which records how something works now and is not "
                   "evidence of where it was first published")
    if missing := [k for k in ("title", "creators", "published") if not w.get(k)]:
        why.append("its " + ", ".join(missing) + " is not recorded")
    if not _retrieved_itself(s):
        why.append("no passage from this work has been retrieved and matched verbatim by Loom itself")
    if verdict == "no" or detail.get("identity_correct") == "no" or detail.get("role_correct") == "no":
        why.append("a separate attribution review judged its identity or its role to be wrong")
        disputed = True
    elif verdict == "stale":
        why.append("the attribution review judged an earlier version of this evidence, and what it judged has since changed")
    elif verdict == "partly":
        why.append("the attribution review confirmed its identity and role only in part")
    elif verdict in (None, "not_judged"):
        why.append("no separate attribution review has confirmed its identity and role")
    elif verdict != "yes":
        # Only the one verdict Loom writes counts. Anything else — a value from an older build, a typo, something
        # a future change introduces — is not a confirmation, so it does not establish an origin.
        why.append(f"the attribution review returned {verdict!r}, which is not a confirmation Loom recognises")
    elif detail_unreadable:
        why.append("the attribution review's own detail could not be read, so its confirmation cannot be relied on")
    elif detail.get("identity_correct") != "yes" or detail.get("role_correct") != "yes":
        # A bare "yes" with nothing behind it is not a judgement of identity AND role. Both must be affirmative.
        said = {k: detail.get(k) for k in ("identity_correct", "role_correct")}
        why.append("the attribution review did not affirm both its identity and its role: it recorded "
                   + ", ".join(f"{k.replace('_', ' ')} {v!r}" for k, v in said.items()))
    # An origin cannot be established while the review contradicts itself about who made the work or what kind of
    # work it is. This is deliberately not a fourth origin status: the honest reading is that the origin is NOT
    # established, which is what `unknown` already says. What the extra field adds is why it is unknown — because
    # a person has to decide, not because nobody has looked.
    if _attribution_of(s).get("historyIncomplete"):
        why.append("part of this work's earlier attribution history is missing or unreadable, so an earlier "
                   "disagreement about its identity cannot be ruled out")
    live_identity = [d for d in unresolved_disagreements(s) if d.get("aspect") in SOURCE_WIDE_ASPECTS]
    if live_identity:
        why.extend(_disagreement_why(d) for d in live_identity)
        w["originUnresolved"] = live_identity
    w["originStatus"] = "disputed" if disputed else ("established" if not why else "unknown")
    w["originWhy"] = why
    w["attributionVerdict"] = verdict or "not_judged"
    w["identityEvidence"] = ([{"sourceId": s.get("id"), "url": s.get("url"), "quote": s.get("quote"),
                               "sha256": (s.get("directRetrieval") or {}).get("sha256"),
                               "locator": (s.get("directRetrieval") or {}).get("locator")}] if _retrieved_itself(s) else [])
    return w


def merge_works(works: list) -> dict:
    """One entry per work. The same work seen through several pages keeps every address and every source.

    Contrary evidence is never concealed. A sighting whose attribution review rejected the identity or role makes
    the work disputed however many other sightings looked fine, because a rejection is a finding and not an
    absence. Where one sighting establishes the origin and another did not, the origin stands but the other
    sighting's reasons are kept under `originContrary`, so nothing disappears because of the order they arrived in.
    """
    out: dict = {}
    for w in works:
        cur = out.get(w["id"])
        if cur is None:
            out[w["id"]] = dict(w, originSightings=[{"status": w.get("originStatus"), "why": list(w.get("originWhy") or []),
                                                     "verdict": w.get("attributionVerdict"), "fromSources": list(w.get("fromSources") or []),
                                                     "unresolved": list(w.get("originUnresolved") or [])}])
            continue
        for k in ("seenAt", "fromSources", "originWhy"):
            cur[k] = list(dict.fromkeys((cur.get(k) or []) + (w.get(k) or [])))
        cur["identityEvidence"] = (cur.get("identityEvidence") or []) + (w.get("identityEvidence") or [])
        cur["originSightings"] = (cur.get("originSightings") or []) + [
            {"status": w.get("originStatus"), "why": list(w.get("originWhy") or []),
             "verdict": w.get("attributionVerdict"), "fromSources": list(w.get("fromSources") or []),
             "unresolved": list(w.get("originUnresolved") or [])}]
        for k in ("title", "creators", "published", "version_or_edition", "identifier"):
            if not cur.get(k) and w.get(k):
                cur[k] = w[k]
        if cur.get("role") == "secondary_aid" and w.get("role") != "secondary_aid":
            cur["role"] = w["role"]
    for cur in out.values():
        seen = cur.get("originSightings") or []
        statuses = {x.get("status") for x in seen}
        if "disputed" in statuses:
            # A rejection is a finding. It stands whatever another sighting of the same work looked like.
            cur["originStatus"] = "disputed"
            cur["originWhy"] = list(dict.fromkeys([r for x in seen if x.get("status") == "disputed" for r in x.get("why") or []]))
            cur["originContrary"] = list(dict.fromkeys([r for x in seen if x.get("status") != "disputed" for r in x.get("why") or []]))
        elif live := [d for x in seen for d in x.get("unresolved") or []]:
            # A live contradiction about who made this work, or what kind of work it is, is a finding and not an
            # absence, so it is not outweighed by another sighting that happened to look clean. Several claims
            # read from one document are merged into one work here, so the "other sighting" is often the very
            # same page: letting it establish the origin would settle the contradiction by counting it twice.
            cur["originStatus"] = "unknown"
            cur["originUnresolved"] = live
            cur["originWhy"] = list(dict.fromkeys([r for x in seen if x.get("unresolved") for r in x.get("why") or []]))
            cur["originContrary"] = list(dict.fromkeys([r for x in seen if not x.get("unresolved") for r in x.get("why") or []]))
        elif "established" in statuses:
            cur["originStatus"] = "established"
            cur["originWhy"] = []
            cur["originContrary"] = list(dict.fromkeys([r for x in seen if x.get("status") != "established" for r in x.get("why") or []]))
        else:
            cur["originStatus"] = "unknown"
            cur["originWhy"] = list(dict.fromkeys([r for x in seen for r in x.get("why") or []]))
            cur["originContrary"] = []
        if not cur["originContrary"]:
            cur.pop("originContrary", None)
    return out


def edges_from_sources(sources: list, works: dict, texts: dict | None = None, canonical: dict | None = None) -> list:
    """Every claimed relationship, as an edge between two works, with what it rests on.

    The earlier work named in a lineage entry is matched to a work already known by identifier, then by title. If
    it matches nothing known, the edge still exists and says so: an unmatched earlier work is not invented, and it
    is not silently dropped either.
    """
    by_ident: dict = {}
    for wid, w in works.items():
        for k in {_norm_identifier(w.get("identifier")), ident_key(w.get("identifier"))}:
            if k:
                by_ident.setdefault(k, wid)
    by_title = {_norm(w.get("title")): wid for wid, w in works.items() if _norm(w.get("title"))}
    # One relationship, one edge. A page carrying several claims produces a source record for each of them, and a
    # relationship read from that page is attached to every one of those records: the acceptance course turned 43
    # relationships read from 19 pages into 71 edges, one signature counted four times. Counting the same sentence
    # once for every claim on its page overstates how much evidence of descent there is. Edges are therefore keyed
    # by what they actually assert — the two works, the relation, and the words shown for it — and every source
    # record carrying it is listed, so nothing is lost. One sentence naming two earlier works is still two edges,
    # because those are two different assertions.
    out: list = []
    seen: dict = {}
    for s in sources:
        later = (canonical or {}).get(s.get("id")) or work_id(s)
        for e in s.get("lineage") or []:
            if not isinstance(e, dict):
                continue
            named = e.get("earlier_work")
            earlier = by_ident.get(_norm_identifier(named)) or by_ident.get(ident_key(named)) or by_title.get(_norm(named))
            rel = e.get("relation") if e.get("relation") in RELATIONS else None
            words = _norm(e.get("supporting_words"))
            key = (later, earlier, _norm(named), rel, words)
            edge = {"from": later, "to": earlier, "earlierWorkAsNamed": named, "relation": rel,
                    "whatChanged": e.get("what_changed"), "limits": e.get("limits"),
                    "supportingWords": e.get("supporting_words"), "fromSource": s.get("id")}
            edge.update(judge_edge(edge, s, works, (texts or {}).get(s.get("id"))))
            prior = seen.get(key)
            if prior is None:
                edge["fromSources"] = [s.get("id")]
                seen[key] = edge
                out.append(edge)
                continue
            if s.get("id") not in prior["fromSources"]:
                prior["fromSources"].append(s.get("id"))
            # Contrary evidence is never concealed by merging: if any record of this assertion was judged
            # disputed, the edge is disputed. Otherwise the better-supported reading stands, and the reasons the
            # others gave are kept beside it rather than thrown away.
            for w in edge.get("why") or []:
                if w not in (prior.get("why") or []) and w not in (prior.get("alsoSaid") or []):
                    prior.setdefault("alsoSaid", []).append(w)
            # A contested reading is as sticky as a disputed one. Only `disputed` was protected here, so a
            # record carrying a live contradiction was overwritten by a clean record of the same assertion
            # whenever the clean one happened to be read first, and the standing depended on arrival order.
            if _RANK.get(edge["status"], 2) < _RANK.get(prior["status"], 2) or \
                    (prior["status"] not in _STICKY and _RANK.get(edge["status"], 2) > _RANK.get(prior["status"], 2)):
                prior.update({k: edge[k] for k in ("status", "why", "fromSource", "whatChanged", "limits")})
                # The reasons travel with the status they explain. Adopting `unresolved` without the record of
                # what was contradicted, or dropping that record when a reading moves off `unresolved`, would
                # leave an edge whose standing nobody can account for.
                for k in ("unresolvedDisagreements", "wouldBeWithoutTheDisagreement"):
                    if k in edge:
                        prior[k] = edge[k]
                    else:
                        prior.pop(k, None)
    return out


def disagreement_key(aspect: str, earlier_work=None, relation=None) -> str:
    """One stable name for the thing two runs disagreed about.

    The key is what makes a disagreement survive. Comparing a run only against the run before it lets a
    contradiction vanish by repetition: answer yes, then no, then no again, and the last two agree, so by the
    third run nothing looks wrong even though the first two still contradict each other on the same evidence.
    Carrying unresolved disagreements forward under a stable key closes that, and it is also what a resolution is
    recorded against, so deciding one question does not silently settle a different one.
    """
    if aspect != "relationship":
        return aspect
    return "relationship|" + ident_key(earlier_work) + "|" + _norm(relation)


def _attribution_of(s: dict) -> dict:
    """A source's attribution record, or an empty one. A record of the wrong shape tells us nothing."""
    a = s.get("attribution") if isinstance(s, dict) else None
    return a if isinstance(a, dict) else {}


def unresolved_disagreements(s: dict, edge: dict | None = None) -> list:
    """The live contradictions that bear on this edge, or on the source's identity when no edge is given.

    Source-wide aspects — identity, role, the overall verdict, whether the page supports descent at all — bear on
    everything read from that source. A contradiction about ONE relationship bears on that relationship only:
    unsettling a page's other claims because one of them is contested would throw away evidence that nothing is
    actually wrong with, which is the opposite of what keeping disagreement is for.

    Anything stored here that cannot be read is treated as a live contradiction rather than as no contradiction.
    A malformed record is not a clean bill of health.
    """
    items = _attribution_of(s).get("unresolvedDisagreements")
    if items is None:
        return []
    if not isinstance(items, list):
        return [{"aspect": "overall", "key": "overall", "unreadable": True,
                 "note": "This source carries a record of disagreement that Loom cannot read, so nothing resting "
                         "on it can be called settled."}]
    out = []
    for d in items:
        if not isinstance(d, dict):
            out.append({"aspect": "overall", "key": "overall", "unreadable": True,
                        "note": "This source carries a record of disagreement that Loom cannot read, so nothing "
                                "resting on it can be called settled."})
            continue
        aspect = d.get("aspect")
        if aspect in SOURCE_WIDE_ASPECTS:
            out.append(d)
        elif aspect == "relationship":
            if edge is None:
                continue
            if d.get("key") == disagreement_key("relationship", edge.get("earlierWorkAsNamed"), edge.get("relation")):
                out.append(d)
        else:
            # An aspect from a newer build, or a damaged one. Loom cannot tell what it bears on, so it bears on
            # everything from this source.
            out.append(dict(d, aspect="overall", key=str(d.get("key") or "overall"), unrecognisedAspect=aspect))
    return out


def _disagreement_why(d: dict) -> str:
    """One plain sentence a reader can act on, naming the two answers and whether the question was the same."""
    if d.get("unreadable"):
        return str(d.get("note") or "a record of disagreement on this source cannot be read")
    what = {"identity": "who made this source", "role": "what kind of source it is",
            "overall": "this source overall", "lineage_supported": "whether this page supports descent at all"}.get(
        d.get("aspect"), "this relationship")
    pair = f"{d.get('earlier')!r} earlier and {d.get('later')!r} now"
    if d.get("sameWholeRequest") is False:
        return (f"two runs of the attribution review disagree about {what} ({pair}) on the same evidence, and the "
                f"rest of the request changed between them as well, so neither answer has been established; a "
                f"person decides")
    return (f"two runs of the attribution review disagree about {what} ({pair}) on the same evidence and the same "
            f"request, and nobody has decided between them")


def judge_edge(edge: dict, s: dict, works: dict, text: str | None = None) -> dict:
    """Whether a claimed relationship is supported, with the reasons. Nothing unestablished becomes supported."""
    why = []
    if not edge.get("relation"):
        why.append("the relationship is not one Loom records")
    if not edge.get("to"):
        why.append("the earlier work it names is not a work Loom holds, so the link has no other end")
    if not _retrieved_itself(s):
        why.append("the claim rests on a page Loom has not retrieved and matched verbatim itself")
    if (s.get("role") or "secondary_aid") == "secondary_aid":
        why.append("a secondary aid can point at an original but is not evidence for it")
    words = str(edge.get("supportingWords") or "").strip()
    # Checked against the whole retrieved page where Loom still holds it. The short excerpt kept on a source is
    # only the context around its quotation, so judging against that alone rejected words that really are there.
    against = text if text is not None else s.get("directExcerpt")
    if not words:
        why.append("no words from the page were given to show it")
    elif against and " ".join(words.lower().split()) not in " ".join(str(against).lower().split()):
        why.append("the words given to show it are not in the text Loom retrieved")
    # An attribution record of the wrong shape used to raise here and take the whole graph down with it. A
    # damaged record tells us nothing, which is not the same as telling us everything is fine: it fails closed.
    att = _attribution_of(s)
    av = att.get("verdict")
    raw_detail = att.get("detail")
    detail = raw_detail if isinstance(raw_detail, dict) else {}
    # The reviewer judges each claimed relationship on its own evidence. Use THAT judgement for this edge where it
    # exists: a page carrying one weak claim used to drag down every other claim on it, so a relationship whose
    # words were shown verbatim still counted as unsupported. Identity and role are still judged per source, because
    # they are properties of the source; only the relationship judgement is per relationship.
    mine = _relationship_verdict(detail, edge)
    if av == "stale":
        why.append("the attribution review judged an earlier version of this evidence")
    elif av == "not_judged":
        why.append("the attribution review returned no judgement for this source")
    elif mine == "no" or (mine is None and detail.get("lineage_supported") == "no"):
        return {"status": "disputed", "why": ["the attribution review judged this relationship unsupported"]}
    elif mine == "yes":
        pass  # this relationship was confirmed on its own words
    elif mine == "partly":
        why.append("the attribution review confirmed THIS relationship only in part: " + _reason_for(detail, edge))
    elif mine == "cannot_tell":
        why.append("the attribution review could not tell from the words shown whether this relationship holds")
    elif av == "partly":
        why.append("the attribution review confirmed this relationship only in part: " + str(detail.get("reason") or "").strip()[:200])
    elif av not in ("yes",):
        why.append("no attribution review has confirmed this relationship")
    # Identity and role belong to the source and gate everything that rests on it. Two things were wrong here.
    #
    # The check ran only when the source verdict was not already "yes", and it read a MISSING field as a pass:
    # `not in ("yes", None)` lets None through. So a relationship whose review never judged who made the source,
    # or what kind of source it is, came out supported on the strength of the fields nobody had filled in. An
    # omitted judgement is not a favourable one. Both fields must now say "yes" in so many words, on every edge,
    # and anything else — missing, empty, "cannot_tell", a value from some other build, a detail block that is
    # not readable at all — fails closed.
    for field, label in (("identity_correct", "identity"), ("role_correct", "role")):
        got = detail.get(field)
        if got == "yes":
            continue
        said = "recorded nothing about it" if got is None else f"recorded {got!r}"
        why.append(f"the attribution review did not affirm the source's {label}: it {said}, and a relationship "
                   f"cannot rest on a source whose {label} is unconfirmed")
    if _attribution_of(s).get("historyIncomplete"):
        why.append("part of this source's earlier attribution history is missing or unreadable, so an earlier "
                   "disagreement about this relationship cannot be ruled out")
    status = "supported" if not why else "unknown"
    # An unresolved disagreement is not outweighed by a clean-looking later answer. Where two runs gave different
    # answers to the same question on the same evidence and nobody has decided between them, the claim is held at
    # `unresolved`: the latest answer does not win by being latest, nothing is averaged, and no third run is asked
    # in the hope of a tie-break. A disputed edge is left disputed, because that is already a finding against it.
    live = unresolved_disagreements(s, edge)
    if live and status != "disputed":
        return {"status": "unresolved",
                "why": why + [_disagreement_why(d) for d in live],
                "unresolvedDisagreements": live,
                "wouldBeWithoutTheDisagreement": status}
    return {"status": status, "why": why}


def _relationship_entry(detail: dict, edge: dict) -> dict | None:
    """The reviewer's judgement of THIS relationship, matched on the earlier work it names and the relation."""
    named, rel = _norm(edge.get("earlierWorkAsNamed")), _norm(edge.get("relation"))
    rels = (detail or {}).get("relationships")
    if not isinstance(rels, list):
        return None
    for r in rels:
        if not isinstance(r, dict):
            continue
        if _norm(r.get("relation")) == rel and (
                _norm(r.get("earlier_work")) == named or ident_key(r.get("earlier_work")) == ident_key(edge.get("earlierWorkAsNamed"))):
            return r
    return None


def _relationship_verdict(detail: dict, edge: dict):
    r = _relationship_entry(detail, edge)
    v = (r or {}).get("supported")
    return v if v in ("yes", "partly", "no", "cannot_tell") else None


def _reason_for(detail: dict, edge: dict) -> str:
    r = _relationship_entry(detail, edge) or {}
    return str(r.get("reason") or (detail or {}).get("reason") or "").strip()[:200]


def build(sources: list, texts: dict | None = None) -> dict:
    """The whole picture: the works, how they descend, and what is still not established."""
    canonical = canonical_work_ids(sources or [])
    works = merge_works([work_from_source(s, canonical) for s in sources or []])
    edges = edges_from_sources(sources or [], works, texts, canonical)
    originals = [w for w in works.values() if w.get("role") == "original_contribution" and w.get("originStatus") == "established"]
    return {"works": works, "edges": edges,
            "summary": {"works": len(works), "originalsEstablished": len(originals),
                        "descentEdges": len([e for e in edges if e.get("relation") in DESCENT]),
                        "supportedEdges": len([e for e in edges if e["status"] == "supported"]),
                        "unresolvedEdges": len([e for e in edges if e["status"] == "unresolved"]),
                        "unknownEdges": len([e for e in edges if e["status"] == "unknown"]),
                        "disputedEdges": len([e for e in edges if e["status"] == "disputed"]),
                        # Counted separately so a reader can see at a glance that some of this graph is waiting on
                        # a person rather than on more research.
                        "worksWithUnresolvedIdentity": len([w for w in works.values() if w.get("originUnresolved")])}}


def chains(built: dict) -> list:
    """Each established original with the later works that are supported as extending, correcting or replicating it.

    This is the thing the requirement asks to see working: an original, and the documented extensions hanging off
    it, each one carrying the locator that supports it.
    """
    works, out = built["works"], []
    for w in works.values():
        if w.get("role") != "original_contribution" or w.get("originStatus") != "established":
            continue
        later = [{"work": e["from"], "title": (works.get(e["from"]) or {}).get("title"), "relation": e["relation"],
                  "whatChanged": e.get("whatChanged"), "supportingWords": e.get("supportingWords"), "status": e["status"]}
                 for e in built["edges"] if e.get("to") == w["id"] and e.get("relation") in DESCENT]
        out.append({"original": {"work": w["id"], "title": w.get("title"), "creators": w.get("creators"), "published": w.get("published"),
                                 "identifier": w.get("identifier")},
                    "supportedExtensions": [x for x in later if x["status"] == "supported"],
                    # An extension held at `unresolved` is listed among the ones not established, because it is
                    # not established; it is also named on its own, so nobody has to read the whole list to find
                    # the ones that are waiting on a person rather than on better evidence.
                    "awaitingAPersonsDecision": [x for x in later if x["status"] == "unresolved"],
                    "claimedButNotEstablished": [x for x in later if x["status"] != "supported"]})
    return out
