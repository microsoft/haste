import unittest
import uuid

from hastegeo.core.models.publishing import (
    PublishMetadataUpdate,
    PublishRequest,
    SourceImageryRef,
    is_https_url,
)
from hastegeo.core.publishing.open_data import (
    OPEN_DATA_PROGRAMS,
    validate_source_refs,
)


def _ref(program_id: str, href: str, **kwargs) -> SourceImageryRef:
    return SourceImageryRef(programId=program_id, href=href, **kwargs)


class TestSourceImageryRef(unittest.TestCase):
    def test_requires_https_href(self) -> None:
        with self.assertRaises(ValueError):
            _ref("vantor-open-data", "http://insecure.example/x.json")
        with self.assertRaises(ValueError):
            _ref("vantor-open-data", "not-a-url")

    def test_accepts_https_href(self) -> None:
        ref = _ref("vantor-open-data", " https://a.example/x.json ")
        self.assertEqual(ref.href, "https://a.example/x.json")


class TestValidateSourceRefs(unittest.TestCase):
    def test_drops_unregistered_program(self) -> None:
        refs = [
            _ref("vantor-open-data", "https://a.example/1.json"),
            _ref("commercial-vendor", "https://a.example/2.json"),
        ]
        out = validate_source_refs(refs)
        self.assertEqual([r.programId for r in out], ["vantor-open-data"])

    def test_stamps_canonical_and_ignores_client_values(self) -> None:
        # Client claims attribution + a bogus permissive license; registry wins.
        ref = _ref(
            "vantor-open-data",
            "https://a.example/1.json",
            programName="Totally Free Imagery",
            license="CC0-1.0",
            attributable=True,
        )
        out = validate_source_refs([ref])[0]
        self.assertEqual(
            out.programName, OPEN_DATA_PROGRAMS["vantor-open-data"]["name"]
        )
        self.assertEqual(out.license, "CC-BY-NC-4.0")
        self.assertTrue(out.attributable)

    def test_dedupes_by_program_and_href(self) -> None:
        refs = [
            _ref("planet-open-data", "https://a.example/1.json"),
            _ref("planet-open-data", "https://a.example/1.json"),
            _ref("planet-open-data", "https://a.example/2.json"),
        ]
        out = validate_source_refs(refs)
        self.assertEqual([r.href for r in out], [
            "https://a.example/1.json",
            "https://a.example/2.json",
        ])

    def test_empty_and_none(self) -> None:
        self.assertEqual(validate_source_refs(None), [])
        self.assertEqual(validate_source_refs([]), [])


class TestCitationNormalization(unittest.TestCase):
    def _request(self, citation) -> PublishRequest:
        return PublishRequest(
            requestId=uuid.uuid4(),
            projectId=uuid.uuid4(),
            imageLayerId="layer-1",
            modelId="7",
            name="n",
            target="local",
            artifacts=["gpkg"],
            sourceImageryCitation=citation,
        )

    def test_request_trims_and_empties_to_none(self) -> None:
        self.assertIsNone(self._request("   ").sourceImageryCitation)
        self.assertIsNone(self._request(None).sourceImageryCitation)
        self.assertEqual(
            self._request("  Some citation ").sourceImageryCitation,
            "Some citation",
        )

    def test_update_citation_normalizes(self) -> None:
        update = PublishMetadataUpdate(
            projectId=uuid.uuid4(),
            datasetId=uuid.uuid4(),
            sourceImageryCitation="  https://example.org/x  ",
        )
        self.assertEqual(
            update.sourceImageryCitation, "https://example.org/x"
        )

    def test_is_https_url(self) -> None:
        self.assertTrue(is_https_url("https://example.org/x"))
        self.assertFalse(is_https_url("http://example.org/x"))
        self.assertFalse(is_https_url("just text"))
        self.assertFalse(is_https_url(None))


if __name__ == "__main__":
    unittest.main()
