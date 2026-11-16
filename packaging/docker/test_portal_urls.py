import unittest
from portal_urls import portal_urls,setup_links


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

    def test_setup_output_labels_one_pc_link_and_one_host_link(self):
        value=setup_links('http://127.0.0.1:8088/?t=synthetic-only','172.25.199.100')
        self.assertIn('Open setup on this PC:\n  http://127.0.0.1:8088/?t=synthetic-only',value)
        self.assertIn('Direct Linux/WSL host address:\n  http://172.25.199.100:8088/?t=synthetic-only',value)
        self.assertEqual(value.count('http://'),2)

    def test_missing_host_route_does_not_offer_an_arbitrary_bridge_address(self):
        value=setup_links('http://127.0.0.1:8088/?t=synthetic-only')
        self.assertEqual(value.count('http://'),1)
        self.assertNotIn('Direct Linux/WSL',value)
