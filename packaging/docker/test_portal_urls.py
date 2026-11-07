import unittest
from portal_urls import portal_urls


class PortalUrlsTests(unittest.TestCase):
    def test_ip_links_preserve_authentication_and_port(self):
        self.assertEqual(portal_urls('http://127.0.0.1:18765/?t=synthetic-only', ['192.0.2.23']),
                         ['http://127.0.0.1:18765/?t=synthetic-only', 'http://192.0.2.23:18765/?t=synthetic-only'])

    def test_unusable_addresses_and_duplicates_are_omitted(self):
        self.assertEqual(portal_urls('http://127.0.0.1:18765/?t=fixture',
                                    ['127.0.0.1', '0.0.0.0', '::1', '169.254.2.1', '224.0.0.1', 'bad', '192.0.2.23', '192.0.2.23']),
                         ['http://127.0.0.1:18765/?t=fixture', 'http://192.0.2.23:18765/?t=fixture'])

    def test_invalid_local_url_is_rejected(self):
        for url in ['http://+:18765/', 'http://192.0.2.23:18765/', 'https://127.0.0.1:18765/', 'http://127.0.0.1/']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                portal_urls(url, [])
