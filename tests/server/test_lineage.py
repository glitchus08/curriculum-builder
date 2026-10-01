"""Works, their origins, and how later works descend from them.

These are pure checks on the lineage rules. They use invented works, so nothing here claims anything about a real
publication; the real-source exercise is separate.
"""
import unittest

from loom_server import lineage


def src(**kw):
    """A source record that HAS been retrieved and matched verbatim, unless a test says otherwise."""
    base = {"id": "S1", "url": "https://example.org/a", "title": "A first report", "authors": ["Ada Ito"], "published": "1998-03-01",
            "version_or_edition": "1", "identifier": "doi:10.1234/first", "role": "original_contribution",
            "quote": "we introduce the method described here", "evidenceLevel": "direct_text_quote_found",
            "directRetrieval": {"sha256": "a" * 64, "quoteVerbatim": True, "locator": {"charStart": 5, "charEnd": 40}},
            "directExcerpt": "we introduce the method described here and give its limits",
            "attribution": {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes"}}, "lineage": []}
    base.update(kw)
    return base


class WorkIdentity(unittest.TestCase):
    def test_the_same_work_reached_through_two_addresses_is_one_work(self):
        a = src(url="https://example.org/a", id="S1")
        b = src(url="https://mirror.example.net/a-copy", id="S2")
        self.assertEqual(lineage.work_id(a), lineage.work_id(b), "a published identifier decides which work it is")
        works = lineage.merge_works([lineage.work_from_source(a), lineage.work_from_source(b)])
        self.assertEqual(len(works), 1)
        w = next(iter(works.values()))
        self.assertEqual(sorted(w["seenAt"]), ["https://example.org/a", "https://mirror.example.net/a-copy"])
        self.assertEqual(sorted(w["fromSources"]), ["S1", "S2"])

    def test_an_identifier_is_compared_in_one_form(self):
        for a, b in [("doi:10.1234/x", "https://doi.org/10.1234/X"), ("urn:isbn:9781234567897", "isbn:978-1234567897"),
                     ("arxiv:2401.00001", "arxiv.org/abs/2401.00001")]:
            self.assertEqual(lineage.work_id({"identifier": a}), lineage.work_id({"identifier": b}), f"{a} vs {b}")

    def test_without_an_identifier_the_title_creator_and_date_decide_and_the_address_does_not(self):
        a = {"title": "A first report", "authors": ["Ada Ito"], "published": "1998", "url": "https://one.example/x"}
        b = dict(a, url="https://two.example/y")
        self.assertEqual(lineage.work_id(a), lineage.work_id(b), "a work is not its address")
        self.assertNotEqual(lineage.work_id(a), lineage.work_id(dict(a, published="1999")))

    def test_an_established_origin_carries_no_reasons_why_it_is_not_established(self):
        """Whichever order the sightings arrive in. A work that is established and also lists why it is not would
        be read as unestablished by anyone skimming the reasons."""
        strong = lineage.work_from_source(src(id="S1"))
        weak = lineage.work_from_source(src(id="S2", evidenceLevel="tool_summary", directRetrieval={}))
        self.assertEqual(strong["originStatus"], "established")
        self.assertEqual(weak["originStatus"], "unknown")
        for order in ([strong, weak], [weak, strong]):
            w = lineage.merge_works(order)[strong["id"]]
            self.assertEqual((w["originStatus"], w["originWhy"]), ("established", []))

    def test_a_work_is_an_established_origin_only_when_its_identity_and_its_own_text_are_in_hand(self):
        self.assertEqual(lineage.work_from_source(src())["originStatus"], "established")
        self.assertEqual(lineage.work_from_source(src(role="secondary_aid"))["originStatus"], "unknown")
        self.assertIn("secondary aid", lineage.work_from_source(src(role="secondary_aid"))["originWhy"][0])
        self.assertEqual(lineage.work_from_source(src(published=None))["originStatus"], "unknown")
        no_text = src(evidenceLevel="tool_summary", directRetrieval={})
        self.assertEqual(lineage.work_from_source(no_text)["originStatus"], "unknown")
        self.assertIn("retrieved and matched verbatim", lineage.work_from_source(no_text)["originWhy"][0])
        self.assertEqual(lineage.work_from_source(no_text)["identityEvidence"], [], "nothing stands as its evidence")


class OriginNeedsConfirmedAttribution(unittest.TestCase):
    """Codex reproduced an origin marked established while the attribution review had rejected it outright."""

    BASE = {"id": "S1", "url": "https://e.org/x", "title": "A paper", "authors": ["Ada Ito"], "published": "1998",
            "identifier": "doi:10.1234/first", "role": "original_contribution", "evidenceLevel": "direct_text_quote_found",
            "quote": "we introduce the method described here", "directExcerpt": "we introduce the method described here",
            "directRetrieval": {"quoteVerbatim": True, "sha256": "f" * 64}, "lineage": []}

    def w(self, attribution, **kw):
        return lineage.work_from_source(dict(self.BASE, attribution=attribution, **kw))

    def test_only_the_exact_confirmation_establishes_an_origin_and_anything_else_fails_closed(self):
        """Codex reproduced a bare verdict 'yes' with an empty detail, and a verdict of 'unexpected', both
        establishing an origin. A malformed detail raised instead of failing closed."""
        for attribution in [{"verdict": "yes", "detail": {}},
                            {"verdict": "unexpected", "detail": {}},
                            {"verdict": "yes", "detail": {"role_correct": "yes"}},
                            {"verdict": "yes", "detail": {"identity_correct": "yes"}},
                            {"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "partly"}},
                            {"verdict": "yes", "detail": {"identity_correct": "cannot_tell", "role_correct": "yes"}},
                            {"verdict": "yes", "detail": "not a mapping"},
                            {"verdict": "yes", "detail": [1, 2]},
                            "not a mapping at all",
                            {}]:
            w = self.w(attribution)
            self.assertEqual(w["originStatus"], "unknown", attribution)
            self.assertTrue(w["originWhy"], "and it says why")
        w = self.w({"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}})
        self.assertEqual((w["originStatus"], w["originWhy"]), ("established", []), "only both affirmed establishes it")

    def test_a_bare_confirmation_does_not_establish_an_origin_through_the_built_chain_or_the_export(self):
        bare = dict(self.BASE, attribution={"verdict": "yes", "detail": {}})
        built = lineage.build([bare])
        w = next(iter(built["works"].values()))
        self.assertEqual(w["originStatus"], "unknown")
        self.assertEqual(built["summary"]["originalsEstablished"], 0, "not counted as an original")
        self.assertEqual(lineage.chains(built), [], "and carries no chain")

    def test_a_rejected_attribution_makes_the_origin_disputed_never_established(self):
        w = self.w({"verdict": "no", "detail": {"identity_correct": "no", "role_correct": "no"}})
        self.assertEqual(w["originStatus"], "disputed")
        self.assertIn("judged its identity or its role to be wrong", w["originWhy"][0])

    def test_missing_stale_partial_and_undecided_attribution_all_leave_the_origin_unknown(self):
        for attribution, expect in [(None, "no separate attribution review"),
                                    ({"verdict": "not_judged", "detail": {}}, "no separate attribution review"),
                                    ({"verdict": "stale", "detail": {}}, "earlier version of this evidence"),
                                    ({"verdict": "partly", "detail": {}}, "only in part"),
                                    ({"verdict": "yes", "detail": {"identity_correct": "cannot_tell"}}, "did not affirm both")]:
            w = self.w(attribution)
            self.assertEqual(w["originStatus"], "unknown", attribution)
            self.assertTrue(any(expect in r for r in w["originWhy"]), (attribution, w["originWhy"]))

    def test_only_a_confirmed_identity_and_role_establishes_an_origin(self):
        w = self.w({"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}})
        self.assertEqual((w["originStatus"], w["originWhy"]), ("established", []))

    def test_current_official_documentation_is_not_evidence_of_historical_invention(self):
        w = self.w({"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}}, role="official_documentation")
        self.assertEqual(w["originStatus"], "unknown")
        self.assertIn("not evidence of where it was first published", w["originWhy"][0])

    def test_a_rejection_is_not_concealed_by_another_sighting_of_the_same_work(self):
        good = self.w({"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}})
        bad = lineage.work_from_source(dict(self.BASE, id="S2", url="https://mirror.example/x",
                                            attribution={"verdict": "no", "detail": {"identity_correct": "no"}}))
        for order in ([good, bad], [bad, good]):
            w = lineage.merge_works(order)[good["id"]]
            self.assertEqual(w["originStatus"], "disputed", "whichever order they arrived in")

    def test_a_sighting_without_confirmation_is_kept_visible_beside_an_established_one(self):
        good = self.w({"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes"}})
        weak = lineage.work_from_source(dict(self.BASE, id="S3", url="https://m2.example/x", attribution=None))
        w = lineage.merge_works([good, weak])[good["id"]]
        self.assertEqual(w["originStatus"], "established")
        self.assertTrue(any("no separate attribution review" in r for r in w.get("originContrary") or []),
                        "the unconfirmed sighting is not erased")

    def test_a_rejected_origin_carries_no_chain_and_shows_as_disputed_in_the_built_state(self):
        rejected = dict(self.BASE, attribution={"verdict": "no", "detail": {"identity_correct": "no"}})
        later = dict(self.BASE, id="S9", url="https://e.org/y", title="A later work", identifier="doi:10.1234/second",
                     authors=["Bo Lin"], published="2011", role="primary_extension",
                     quote="we repeat the 1998 method over ten more years",
                     directExcerpt="we repeat the 1998 method over ten more years",
                     attribution={"verdict": "yes", "detail": {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes"}},
                     lineage=[{"relation": "replicated", "earlier_work": "doi:10.1234/first", "what_changed": "more years",
                               "supporting_words": "we repeat the 1998 method"}])
        built = lineage.build([rejected, later])
        w = built["works"][lineage.work_id(rejected)]
        self.assertEqual(w["originStatus"], "disputed")
        self.assertEqual(built["summary"]["originalsEstablished"], 0, "a disputed work is not counted as an original")
        self.assertEqual(lineage.chains(built), [], "and it carries no chain of extensions")


class Descent(unittest.TestCase):
    def chain(self, **later_kw):
        original = src(id="S1", identifier="doi:10.1234/first", title="A first report")
        later = src(id="S2", url="https://example.org/b", title="A wider replication", identifier="doi:10.1234/second",
                    authors=["Bo Lin"], published="2011-06-01", role="primary_extension",
                    quote="we repeat the 1998 method over ten more years",
                    directExcerpt="we repeat the 1998 method over ten more years, and the effect is smaller",
                    lineage=[{"relation": "replicated", "earlier_work": "doi:10.1234/first",
                              "what_changed": "ten more years of data", "supporting_words": "we repeat the 1998 method",
                              "limits": "one region only"}])
        later.update(later_kw)
        return lineage.build([original, later])

    def test_an_original_and_a_supported_replication_form_a_chain_with_its_locator(self):
        built = self.chain()
        self.assertEqual(built["summary"]["originalsEstablished"], 1)
        self.assertEqual(built["summary"]["supportedEdges"], 1)
        e = built["edges"][0]
        self.assertEqual((e["relation"], e["status"]), ("replicated", "supported"))
        self.assertEqual(e["to"], lineage.work_id({"identifier": "doi:10.1234/first"}), "the edge points at the original work")
        ch = lineage.chains(built)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["original"]["title"], "A first report")
        self.assertEqual(len(ch[0]["supportedExtensions"]), 1)
        self.assertEqual(ch[0]["supportedExtensions"][0]["whatChanged"], "ten more years of data")
        self.assertEqual(ch[0]["claimedButNotEstablished"], [])

    def test_a_secondary_summary_can_point_at_an_original_but_never_becomes_its_evidence(self):
        built = self.chain(role="secondary_aid")
        e = built["edges"][0]
        self.assertEqual(e["status"], "unknown")
        self.assertIn("a secondary aid can point at an original but is not evidence for it", e["why"])
        self.assertEqual(lineage.chains(built)[0]["supportedExtensions"], [])
        self.assertEqual(len(lineage.chains(built)[0]["claimedButNotEstablished"]), 1, "the claim is kept, not dropped")

    def test_words_that_are_not_in_the_retrieved_text_do_not_support_a_relationship(self):
        e = self.chain(supporting_words=None, lineage=[{"relation": "replicated", "earlier_work": "doi:10.1234/first",
                                                        "what_changed": "x", "supporting_words": "we disprove the 1998 method"}])["edges"][0]
        self.assertEqual(e["status"], "unknown")
        self.assertIn("the words given to show it are not in the text Loom retrieved", e["why"])

    def test_a_relationship_with_no_words_at_all_is_not_supported(self):
        e = self.chain(lineage=[{"relation": "replicated", "earlier_work": "doi:10.1234/first", "what_changed": "x"}])["edges"][0]
        self.assertEqual(e["status"], "unknown")
        self.assertIn("no words from the page were given to show it", e["why"])

    def test_an_earlier_work_loom_does_not_hold_leaves_the_link_open_and_keeps_what_was_claimed(self):
        e = self.chain(lineage=[{"relation": "extended", "earlier_work": "doi:10.9999/unknown-to-loom",
                                 "what_changed": "y", "supporting_words": "we repeat the 1998 method"}])["edges"][0]
        self.assertIsNone(e["to"])
        self.assertEqual(e["earlierWorkAsNamed"], "doi:10.9999/unknown-to-loom", "what was claimed is still on record")
        self.assertIn("the earlier work it names is not a work Loom holds, so the link has no other end", e["why"])

    def test_a_review_that_refused_the_relationship_makes_it_disputed_not_merely_unknown(self):
        e = self.chain(attribution={"verdict": "partly", "detail": {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "no"}})["edges"][0]
        self.assertEqual(e["status"], "disputed")

    def test_a_judgement_made_on_evidence_that_has_since_changed_does_not_support_a_relationship(self):
        e = self.chain(attribution={"verdict": "stale", "detail": {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes"}})["edges"][0]
        self.assertEqual(e["status"], "unknown")
        self.assertIn("the attribution review judged an earlier version of this evidence", e["why"])

    def test_an_unconfirmed_relationship_is_not_supported(self):
        e = self.chain(attribution=None)["edges"][0]
        self.assertEqual(e["status"], "unknown")
        self.assertIn("no attribution review has confirmed this relationship", e["why"])

    def test_origin_implementation_and_validity_are_different_questions(self):
        """Being the historical original says nothing about what the current version is, or whether it still holds."""
        original = src(id="S1", identifier="doi:10.1234/first")
        current = src(id="S2", identifier="doi:10.1234/docs", title="The maintained specification", role="official_documentation",
                      authors=["The Body"], published="2026-01-01", version_or_edition="v9",
                      quote="this specification supersedes earlier descriptions",
                      directExcerpt="this specification supersedes earlier descriptions of the method",
                      lineage=[{"relation": "superseded", "earlier_work": "doi:10.1234/first", "what_changed": "the current wording",
                                "supporting_words": "this specification supersedes earlier descriptions"}])
        built = lineage.build([original, current])
        roles = {w["role"] for w in built["works"].values()}
        self.assertEqual(roles, {"original_contribution", "official_documentation"})
        self.assertEqual(built["summary"]["descentEdges"], 0, "superseding is not a claim of descent from the original")
        self.assertEqual(lineage.chains(built)[0]["supportedExtensions"], [], "the original's chain does not absorb the current spec")


if __name__ == "__main__":
    unittest.main()


class OneDocumentIsOneWork(unittest.TestCase):
    """A page carrying several claims made several works and counted one relationship once per claim.

    The acceptance course read 43 relationships from 19 pages and built 71 edges, one signature counted four times,
    and showed a single NOAA readme as three separate works.
    """

    def _page(self, n=3, **kw):
        """n claims read from ONE retrieved document: same address, same bytes, differing recorded titles."""
        rel = [{"relation": "extended", "earlier_work": "doi:10.1234/first", "what_changed": "adds a case",
                "supporting_words": "we introduce the method described here", "limits": ""}]
        out = []
        for i in range(n):
            out.append(src(id=f"S{i + 10}", url="https://example.org/readme", identifier="",
                           title=f"A title as claim {i} recorded it", role="official_documentation",
                           directRetrieval={"sha256": "c" * 64, "quoteVerbatim": True, "locator": {"charStart": 0, "charEnd": 30}},
                           lineage=rel, **kw))
        return out

    def test_several_claims_read_from_one_document_are_one_work(self):
        built = lineage.build(self._page(3))
        docs = [w for w in built["works"].values() if "https://example.org/readme" in (w.get("seenAt") or [])]
        self.assertEqual(len(docs), 1, "one document is one work, however many claims rest on it")
        self.assertEqual(sorted(docs[0]["fromSources"]), ["S10", "S11", "S12"], "and every claim on it is kept")

    def test_one_relationship_read_from_that_document_is_one_edge(self):
        built = lineage.build(self._page(3))
        ext = [e for e in built["edges"] if e["relation"] == "extended"]
        self.assertEqual(len(ext), 1, "counted once, not once per claim on the page")
        self.assertEqual(sorted(ext[0]["fromSources"]), ["S10", "S11", "S12"], "with every record that carries it")
        self.assertEqual(built["summary"]["descentEdges"], 1)

    def test_one_sentence_naming_two_earlier_works_is_still_two_edges(self):
        pages = self._page(2)
        for s in pages:
            s["lineage"] = [{"relation": "extended", "earlier_work": "doi:10.1234/first", "what_changed": "a",
                             "supporting_words": "we introduce the method described here", "limits": ""},
                            {"relation": "extended", "earlier_work": "doi:10.9999/other", "what_changed": "b",
                             "supporting_words": "we introduce the method described here", "limits": ""}]
        built = lineage.build(pages)
        self.assertEqual(len([e for e in built["edges"] if e["relation"] == "extended"]), 2,
                         "two different assertions, however they share a quotation")

    def test_one_address_holding_two_identified_works_is_not_merged_into_one(self):
        pages = self._page(2)
        pages[0]["identifier"] = "doi:10.1111/aaa"
        pages[1]["identifier"] = "doi:10.2222/bbb"
        built = lineage.build(pages)
        docs = [w for w in built["works"].values() if "https://example.org/readme" in (w.get("seenAt") or [])]
        self.assertEqual(len(docs), 2, "an address really holding two identified works keeps them apart")

    def test_records_without_retrieved_bytes_are_not_merged_on_their_address_alone(self):
        pages = self._page(2)
        for s in pages:
            s["directRetrieval"] = {"quoteVerbatim": False}
            s["evidenceLevel"] = "tool_summary"
        built = lineage.build(pages)
        docs = [w for w in built["works"].values() if "https://example.org/readme" in (w.get("seenAt") or [])]
        self.assertEqual(len(docs), 2, "without bytes Loom cannot say the two records are the same document")

    def test_a_disputed_reading_of_a_relationship_is_not_hidden_by_a_better_one(self):
        pages = self._page(2)
        pages[0]["attribution"] = {"verdict": "no", "detail": {"identity_correct": "yes", "role_correct": "yes",
                                                               "lineage_supported": "no"}}
        built = lineage.build(pages)
        ext = [e for e in built["edges"] if e["relation"] == "extended"]
        self.assertEqual(len(ext), 1)
        self.assertEqual(ext[0]["status"], "disputed", "a rejection is a finding and survives the merge")
        self.assertEqual(built["summary"]["disputedEdges"], 1)

    def test_the_same_address_with_and_without_a_trailing_slash_is_one_document(self):
        """The acceptance course holds one PMC article twice, once with a trailing slash and once without, and
        grouping on the raw text kept them apart as two works and doubled the relationship read from it."""
        pages = self._page(2)
        pages[0]["url"] = "https://example.org/readme/"
        pages[1]["url"] = "https://Example.org/readme"
        built = lineage.build(pages)
        docs = [w for w in built["works"].values() if any("example.org/readme" in (u or "").lower() for u in w.get("seenAt") or [])]
        self.assertEqual(len(docs), 1, "one document, however its address was written down")
        self.assertEqual(len([e for e in built["edges"] if e["relation"] == "extended"]), 1)

    def test_two_genuinely_different_addresses_are_not_folded_together(self):
        pages = self._page(2)
        pages[0]["url"] = "https://example.org/readme"
        pages[1]["url"] = "https://example.org/other"
        pages[1]["directRetrieval"] = dict(pages[1]["directRetrieval"], sha256="d" * 64)
        built = lineage.build(pages)
        seen = {u for w in built["works"].values() for u in w.get("seenAt") or []}
        self.assertIn("https://example.org/readme", seen)
        self.assertIn("https://example.org/other", seen)
        self.assertEqual(len([e for e in built["edges"] if e["relation"] == "extended"]), 2,
                         "two documents each stating it is two edges, not one")


class NamingAnEarlierWork(unittest.TestCase):
    """Which named earlier works can be gone and got, and which never will be."""

    def test_a_published_identifier_gives_the_address_that_serves_the_work(self):
        got = lineage.named_work_address("10.12688/f1000research.3-62.v2")
        self.assertEqual(got["kind"], "doi")
        self.assertEqual(got["identifier"], "doi:10.12688/f1000research.3-62.v2")
        self.assertEqual(got["url"], "https://doi.org/10.12688/f1000research.3-62.v2")
        self.assertEqual(lineage.named_work_address("RFC 2234")["url"], "https://www.rfc-editor.org/rfc/rfc2234.txt")
        self.assertEqual(lineage.named_work_address("arXiv:1907.02035")["url"], "https://arxiv.org/abs/1907.02035")
        self.assertEqual(lineage.named_work_address("doi: 10.1000/xyz.")["url"], "https://doi.org/10.1000/xyz",
                         "a trailing full stop belongs to the sentence, not to the identifier")

    def test_an_idea_is_not_an_address_and_is_never_guessed_at(self):
        for named in ("the computational notebook format", "The Carpentries pre-workshop setup requirement",
                      "writing about statistics guidance", "Barkjohn et al., 2021", "", None):
            self.assertIsNone(lineage.named_work_address(named),
                              f"{named!r} names an idea or a person and a year, not a work Loom can fetch")

    def test_an_isbn_is_recognised_and_left_alone(self):
        got = lineage.named_work_address("ISBN 978-0-13-235088-4")
        self.assertEqual(got["identifier"], "isbn:9780132350884")
        self.assertIsNone(got["url"], "a book has no address that serves its text")
        self.assertIn("not an address", got["why_not_fetched"])

    def test_a_fetched_earlier_work_gives_the_relationship_its_other_end(self):
        later = src(id="S1", url="https://example.org/later", identifier="doi:10.5555/later",
                    title="A later report", role="primary_extension",
                    lineage=[{"relation": "extended", "earlier_work": "doi:10.1234/first", "what_changed": "adds a case",
                              "supporting_words": "we introduce the method described here", "limits": ""}])
        before = lineage.build([later])
        self.assertIsNone(before["edges"][0]["to"], "nothing holds the earlier work yet")
        self.assertIn("the earlier work it names is not a work Loom holds, so the link has no other end",
                      before["edges"][0]["why"])

        earlier = {"id": "NAMED:doi:10.1234/first", "url": "https://doi.org/10.1234/first", "title": "A first report",
                   "authors": ["Ada Ito"], "published": "1998-03-01", "identifier": "doi:10.1234/first",
                   "role": "original_contribution", "evidenceLevel": "direct_text",
                   "directRetrieval": {"sha256": "e" * 64, "quoteVerbatim": None}, "lineage": [],
                   "namedEndpoint": {"identifier": "doi:10.1234/first", "fetched": True, "namedBy": ["S1"]}}
        after = lineage.build([later, earlier])
        edge = [e for e in after["edges"] if e["relation"] == "extended"][0]
        self.assertEqual(edge["to"], lineage.work_id(earlier), "the link now has both ends")
        self.assertNotIn("the earlier work it names is not a work Loom holds, so the link has no other end", edge["why"])

    def test_a_fetched_earlier_work_is_not_an_established_origin_just_for_being_fetched(self):
        earlier = {"id": "NAMED:doi:10.1234/first", "url": "https://doi.org/10.1234/first", "title": "A first report",
                   "authors": ["Ada Ito"], "published": "1998-03-01", "identifier": "doi:10.1234/first",
                   "role": "original_contribution", "evidenceLevel": "direct_text",
                   "directRetrieval": {"sha256": "e" * 64, "quoteVerbatim": None}, "lineage": [],
                   "namedEndpoint": {"identifier": "doi:10.1234/first", "fetched": True, "namedBy": ["S1"]}}
        built = lineage.build([earlier])
        w = built["works"][lineage.work_id(earlier)]
        self.assertEqual(w["originStatus"], "unknown", "no attribution review has judged it")
        self.assertEqual(built["summary"]["originalsEstablished"], 0)
        self.assertIn("no separate attribution review has confirmed its identity and role", w["originWhy"])

    def test_the_spelling_a_document_used_still_finds_the_work_loom_fetched(self):
        """A paper names its predecessor "10.12688/f1000research.3-62.v2" and Loom fetched it as
        "doi:10.12688/...". Another names "RFC 2234" where Loom holds "rfc2234". Comparing those as text left every
        fetched earlier work sitting beside the relationship that named it rather than on the end of it."""
        for named, held in (("10.12688/f1000research.3-62.v2", "doi:10.12688/f1000research.3-62.v2"),
                            ("RFC 2234", "rfc2234"),
                            ("arXiv:1907.02035", "arxiv:1907.02035"),
                            ("https://doi.org/10.1234/first", "doi:10.1234/first")):
            later = src(id="S1", url="https://example.org/later", identifier="doi:10.5555/later",
                        title="A later report", role="primary_extension",
                        lineage=[{"relation": "extended", "earlier_work": named, "what_changed": "adds a case",
                                  "supporting_words": "we introduce the method described here", "limits": ""}])
            earlier = {"id": "NAMED:" + held, "url": "https://example.org/earlier", "title": "A first report",
                       "authors": ["Ada Ito"], "published": "1998", "identifier": held, "role": "original_contribution",
                       "evidenceLevel": "direct_text", "directRetrieval": {"sha256": "e" * 64}, "lineage": []}
            built = lineage.build([later, earlier])
            edge = [e for e in built["edges"] if e["relation"] == "extended"][0]
            self.assertEqual(edge["to"], lineage.work_id(earlier), f"{named!r} names the work held as {held!r}")

    def test_a_name_that_is_not_an_identifier_still_does_not_match_anything(self):
        later = src(id="S1", url="https://example.org/later", identifier="doi:10.5555/later", role="primary_extension",
                    lineage=[{"relation": "extended", "earlier_work": "the computational notebook format",
                              "what_changed": "a", "supporting_words": "we introduce the method described here", "limits": ""}])
        earlier = {"id": "NAMED:doi:10.1234/first", "url": "https://example.org/earlier", "title": "A first report",
                   "authors": ["Ada Ito"], "published": "1998", "identifier": "doi:10.1234/first",
                   "role": "original_contribution", "evidenceLevel": "direct_text",
                   "directRetrieval": {"sha256": "e" * 64}, "lineage": []}
        built = lineage.build([later, earlier])
        self.assertIsNone([e for e in built["edges"] if e["relation"] == "extended"][0]["to"],
                          "an idea does not match a work just because one happens to be held")


class RelationshipsAreJudgedSeparately(unittest.TestCase):
    """One weak claim on a page used to drag every other claim on that page down with it.

    The acceptance course showed it plainly: S81's RFC 8089 relationship was shown verbatim and confirmed, but the
    edge stayed unsupported because a DIFFERENT relationship on the same source — a bare 'See also' line pointing at
    PEP 428 — was weak. The requirement is branching EVIDENCED RELATIONSHIPS, judged on their own evidence.
    """

    def _src(self, rels, detail):
        return src(id="S81", url="https://example.org/later", identifier="doi:10.5555/later",
                   title="A later work", role="primary_extension", quote="we introduce the method described here",
                   directExcerpt="we introduce the method described here and give its limits",
                   lineage=rels, attribution={"verdict": "partly", "detail": detail})

    def _earlier(self, ident, title):
        return {"id": "NAMED:" + ident, "url": "https://example.org/" + ident, "title": title, "authors": ["A"],
                "published": "1998", "identifier": ident, "role": "original_contribution",
                "evidenceLevel": "direct_text", "directRetrieval": {"sha256": "e" * 64}, "lineage": []}

    def test_a_relationship_shown_verbatim_is_supported_though_another_on_the_page_is_weak(self):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""},
                {"relation": "documented", "earlier_work": "pep428", "supporting_words": words, "what_changed": "b", "limits": ""}]
        detail = {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "partly",
                  "reason": "one of the two rests on a bare see-also line",
                  "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"},
                                    {"earlier_work": "pep428", "relation": "documented", "supported": "partly", "reason": "a bare See also line"}]}
        built = lineage.build([self._src(rels, detail), self._earlier("rfc8089", "The file URI Scheme"), self._earlier("pep428", "Pathlib")])
        by = {e["earlierWorkAsNamed"]: e for e in built["edges"]}
        self.assertEqual(by["rfc8089"]["status"], "supported", f"shown verbatim and confirmed: {by['rfc8089']['why']}")
        self.assertEqual(by["pep428"]["status"], "unknown", "and the weak one is still not supported")
        self.assertTrue(any("THIS relationship" in w for w in by["pep428"]["why"]))
        self.assertEqual(built["summary"]["supportedEdges"], 1)

    def test_a_relationship_the_reviewer_rejected_is_disputed_even_beside_a_confirmed_one(self):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""},
                {"relation": "extended", "earlier_work": "pep428", "supporting_words": words, "what_changed": "b", "limits": ""}]
        detail = {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "partly", "reason": "mixed",
                  "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown"},
                                    {"earlier_work": "pep428", "relation": "extended", "supported": "no", "reason": "not in the text"}]}
        built = lineage.build([self._src(rels, detail), self._earlier("rfc8089", "A"), self._earlier("pep428", "B")])
        by = {e["earlierWorkAsNamed"]: e for e in built["edges"]}
        self.assertEqual(by["rfc8089"]["status"], "supported")
        self.assertEqual(by["pep428"]["status"], "disputed", "a rejection is a finding and is not hidden")
        self.assertEqual(built["summary"]["disputedEdges"], 1)

    def test_a_confirmed_relationship_still_cannot_rest_on_a_source_whose_identity_is_unconfirmed(self):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""}]
        detail = {"identity_correct": "partly", "role_correct": "yes", "lineage_supported": "partly", "reason": "who wrote it is unclear",
                  "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"}]}
        built = lineage.build([self._src(rels, detail), self._earlier("rfc8089", "A")])
        e = built["edges"][0]
        self.assertEqual(e["status"], "unknown", "identity and role are properties of the source and still gate it")
        self.assertTrue(any("identity" in w for w in e["why"]), e["why"])

    def test_without_per_relationship_judgement_the_source_level_verdict_still_governs(self):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""}]
        detail = {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "partly", "reason": "older review, no per-relationship detail"}
        built = lineage.build([self._src(rels, detail), self._earlier("rfc8089", "A")])
        self.assertEqual(built["edges"][0]["status"], "unknown", "an older verdict is not promoted by the new field being absent")


class IdentityAndRoleMustBeAffirmed(unittest.TestCase):
    """A question nobody answered is not a question answered favourably.

    The gate used to read `detail.get(field) not in ("yes", None)`, so a MISSING identity or role judgement passed
    it, and the whole check was skipped whenever the source verdict was already "yes". A relationship could
    therefore be called supported although no review had ever said who made the source or what kind of source it
    was. These are fixture-only checks: they say what the rule is, not that any real record was malformed.
    """

    def _src(self, detail, verdict="partly"):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""}]
        return src(id="S81", url="https://example.org/later", identifier="doi:10.5555/later", title="A later work",
                   role="primary_extension", quote=words,
                   directExcerpt="we introduce the method described here and give its limits",
                   lineage=rels, attribution={"verdict": verdict, "detail": detail})

    def _earlier(self):
        return {"id": "NAMED:rfc8089", "url": "https://example.org/rfc8089", "title": "A", "authors": ["A"],
                "published": "1998", "identifier": "rfc8089", "role": "original_contribution",
                "evidenceLevel": "direct_text", "directRetrieval": {"sha256": "e" * 64}, "lineage": []}

    def _edge(self, detail, verdict="partly"):
        return lineage.build([self._src(detail, verdict), self._earlier()])["edges"][0]

    def test_an_omitted_identity_and_role_do_not_pass_the_gate(self):
        e = self._edge({"lineage_supported": "yes", "reason": "the words are there",
                        "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"}]})
        self.assertEqual(e["status"], "unknown", "a missing judgement is not an affirmative one")
        self.assertTrue(any("identity" in w for w in e["why"]), e["why"])
        self.assertTrue(any("role" in w for w in e["why"]), e["why"])

    def test_the_gate_is_not_skipped_when_the_source_verdict_is_already_yes(self):
        e = self._edge({"lineage_supported": "yes",
                        "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"}]},
                       verdict="yes")
        self.assertEqual(e["status"], "unknown", "an aggregate yes does not stand in for the two judgements it is made of")

    def test_cannot_tell_and_an_unrecognised_value_both_fail_closed(self):
        for got in ("cannot_tell", "", "probably", None):
            detail = {"identity_correct": got, "role_correct": "yes", "lineage_supported": "yes",
                      "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"}]}
            self.assertEqual(self._edge(detail)["status"], "unknown", f"identity {got!r} must not support an edge")

    def test_both_affirmed_still_supports_the_edge(self):
        e = self._edge({"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes",
                        "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": "yes", "reason": "shown verbatim"}]})
        self.assertEqual(e["status"], "supported", "the gate must not reject a judgement that really was made")


class AnUnresolvedDisagreementBlocksSupport(unittest.TestCase):
    """Where two runs answered the same question differently on the same evidence, nobody has decided yet.

    The code recorded the disagreement and then ignored it: a per-relationship "yes" from the latest run produced
    a supported edge although an earlier run on identical evidence had said no. The latest answer won by being
    latest, which is the one thing the written rule says must not happen.
    """

    def _built(self, unresolved, rel_supported="yes"):
        words = "we introduce the method described here"
        rels = [{"relation": "applied", "earlier_work": "rfc8089", "supporting_words": words, "what_changed": "a", "limits": ""}]
        detail = {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes",
                  "relationships": [{"earlier_work": "rfc8089", "relation": "applied", "supported": rel_supported, "reason": "shown verbatim"}]}
        s = src(id="S81", url="https://example.org/later", identifier="doi:10.5555/later", title="A later work",
                role="primary_extension", quote=words,
                directExcerpt="we introduce the method described here and give its limits", lineage=rels,
                attribution={"verdict": "yes", "detail": detail, "unresolvedDisagreements": unresolved})
        earlier = {"id": "NAMED:rfc8089", "url": "https://example.org/rfc8089", "title": "A", "authors": ["A"],
                   "published": "1998", "identifier": "rfc8089", "role": "original_contribution",
                   "evidenceLevel": "direct_text", "directRetrieval": {"sha256": "e" * 64}, "lineage": []}
        return lineage.build([s, earlier])

    def _disagreement(self, aspect, earlier_work=None, relation=None, **kw):
        d = {"aspect": aspect, "key": lineage.disagreement_key(aspect, earlier_work, relation),
             "earlier": "no", "later": "yes", "sameEvidence": True, "sameWholeRequest": True}
        d.update(kw)
        return d

    def test_a_contradicted_relationship_is_not_supported_by_the_later_answer(self):
        built = self._built([self._disagreement("relationship", "rfc8089", "applied")])
        e = built["edges"][0]
        self.assertEqual(e["status"], "unresolved", "the later answer does not win by being later")
        self.assertEqual(e["wouldBeWithoutTheDisagreement"], "supported", "what is blocked is recorded, not hidden")
        self.assertEqual(built["summary"]["supportedEdges"], 0)
        self.assertEqual(built["summary"]["unresolvedEdges"], 1)

    def test_a_contradiction_about_identity_or_role_blocks_every_edge_from_that_source(self):
        for aspect in ("identity", "role", "overall", "lineage_supported"):
            built = self._built([self._disagreement(aspect)])
            self.assertEqual(built["edges"][0]["status"], "unresolved", f"{aspect} belongs to the source")

    def test_a_contradiction_about_identity_also_stops_the_origin_being_established(self):
        built = self._built([self._disagreement("identity")])
        w = next(x for x in built["works"].values() if x.get("identifier") == "doi:10.5555/later")
        self.assertEqual(w["originStatus"], "unknown", "an origin is not established while its identity is contested")
        self.assertTrue(w.get("originUnresolved"))

    def test_a_contradiction_about_one_relationship_leaves_the_others_alone(self):
        built = self._built([self._disagreement("relationship", "pep428", "extended")])
        self.assertEqual(built["edges"][0]["status"], "supported",
                         "a contested claim elsewhere on the page is not a reason to throw this one away")

    def test_a_record_of_disagreement_that_cannot_be_read_fails_closed(self):
        for bad in ("something", [{"not": "a disagreement record"}], [None], 7):
            self.assertEqual(self._built(bad)["edges"][0]["status"], "unresolved", f"{bad!r} is not a clean record")

    def test_a_disputed_relationship_stays_disputed_rather_than_becoming_unresolved(self):
        built = self._built([self._disagreement("relationship", "rfc8089", "applied")], rel_supported="no")
        self.assertEqual(built["edges"][0]["status"], "disputed", "a finding against the claim already stands")

    def test_an_unresolved_edge_is_not_counted_as_a_supported_extension(self):
        words = "we introduce the method described here"
        rels = [{"relation": "replicated", "earlier_work": "doi:10.1234/first", "supporting_words": words,
                 "what_changed": "repeated it", "limits": ""}]
        detail = {"identity_correct": "yes", "role_correct": "yes", "lineage_supported": "yes",
                  "relationships": [{"earlier_work": "doi:10.1234/first", "relation": "replicated", "supported": "yes", "reason": "shown"}]}
        later = src(id="S2", url="https://example.org/later", identifier="doi:10.5555/later", title="A later work",
                    role="primary_extension", quote=words,
                    directExcerpt="we introduce the method described here and give its limits", lineage=rels,
                    attribution={"verdict": "yes", "detail": detail,
                                 "unresolvedDisagreements": [self._disagreement("relationship", "doi:10.1234/first", "replicated")]})
        built = lineage.build([src(), later])
        chain = lineage.chains(built)[0]
        self.assertEqual(chain["supportedExtensions"], [], "an undecided extension is not a supported one")
        self.assertEqual(len(chain["awaitingAPersonsDecision"]), 1)
        self.assertEqual(len(chain["claimedButNotEstablished"]), 1)
