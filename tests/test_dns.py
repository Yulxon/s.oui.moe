import runpy
import socket
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
check_dns = runpy.run_path(str(ROOT / 'scripts/check-dns'))['check_dns']
IPV4 = '203.0.113.10'
IPV6 = '2001:db8::10'


def resolver(answers):
    def resolve(domain, port, family, socktype):
        value = answers[family]
        if isinstance(value, Exception):
            raise value
        return [(family, socktype, 6, '', (address, port)) for address in value]
    return resolve


class DnsTests(unittest.TestCase):
    def test_both_families_match_with_ipv6_normalization(self):
        report = check_dns('test.example.com', IPV4, IPV6,
                           resolver({socket.AF_INET: [IPV4], socket.AF_INET6: ['2001:0db8:0:0::0010']}))
        self.assertTrue(report['matches'])

    def test_stale_ipv6_is_reported_separately_from_correct_ipv4(self):
        report = check_dns('test.example.com', IPV4, IPV6,
                           resolver({socket.AF_INET: [IPV4], socket.AF_INET6: ['2001:db8::99']}))
        self.assertFalse(report['matches'])
        self.assertTrue(report['records']['A']['matches'])
        self.assertEqual(report['records']['AAAA']['addresses'], ['2001:db8::99'])
        self.assertEqual(report['records']['AAAA']['expected'], IPV6)

    def test_fake_ip_is_identified(self):
        report = check_dns('test.example.com', IPV4, IPV6,
                           resolver({socket.AF_INET: ['198.18.0.5'], socket.AF_INET6: [IPV6]}))
        self.assertFalse(report['matches'])
        self.assertTrue(report['records']['A']['fake_ip'])

    def test_dns_errors_do_not_hide_the_other_family(self):
        report = check_dns('test.example.com', IPV4, IPV6,
                           resolver({socket.AF_INET: [IPV4],
                                     socket.AF_INET6: socket.gaierror('test lookup failure')}))
        self.assertFalse(report['matches'])
        self.assertTrue(report['records']['A']['matches'])
        self.assertIn('test lookup failure', report['records']['AAAA']['error'])
